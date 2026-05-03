"""任务管理路由（v2 Phase B）

端点:
- POST   /api/tasks                       — 提交新任务（异步执行 Pipeline）
- GET    /api/tasks                       — 列出所有任务
- GET    /api/tasks/{task_id}             — 获取任务详情（含 progress）
- GET    /api/tasks/{task_id}/transcript  — 读取磁盘 transcript（JSONL 事件流）
- DELETE /api/tasks/{task_id}             — 取消任务（cancel asyncio.Task）

实现要点:
- 用 core.task.TaskRegistry 替代旧的 _tasks 字典
- 用 core.task.TranscriptWriter 把 step 事件落到 workspace/tasks/{task_id}.jsonl
- DELETE 真正 cancel 后台 asyncio.Task；finally 块捕获 CancelledError 把状态置 KILLED
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ..schemas import APIResponse, TaskSubmitRequest
from ..dependencies import get_capability_registry, get_pipeline
from ..websocket.handlers import broadcast_monitor_event
from core.task import (
    TaskRegistry,
    TaskStatus,
    TaskType,
    TranscriptWriter,
    read_transcript,
    reset_parent_task_id,
    set_parent_task_id,
    transcript_path,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

logger = logging.getLogger(__name__)

# 进程内单例：所有任务的注册中心
_registry = TaskRegistry()


def get_task_registry() -> TaskRegistry:
    """暴露给测试与其他模块使用。"""
    return _registry


# ─── 提交 ─────────────────────────────────────────────


@router.post("", response_model=APIResponse)
async def submit_task(req: TaskSubmitRequest):
    """提交新任务，返回 task_id。

    流程:
    1. 选定管线模板（auto → code_generation_and_review）
    2. TaskRegistry 创建 PENDING 状态的 TaskState
    3. asyncio.create_task 后台跑 Pipeline；attach 句柄到 registry
    """
    pipeline = get_pipeline()
    cap_registry = get_capability_registry()

    template_name = req.pipeline if req.pipeline != "auto" else "code_generation_and_review"

    state = _registry.create(
        task_type=TaskType.PIPELINE,
        requirement=req.requirement,
        pipeline_name=template_name,
    )
    state.output_file = str(transcript_path(state.id))
    writer = TranscriptWriter(state.id)
    writer.write("created", {"requirement": req.requirement, "pipeline": template_name})

    if pipeline is None:
        _registry.mark_done(state.id, TaskStatus.FAILED, error="Pipeline 未初始化")
        writer.write("error", {"error": "Pipeline 未初始化"})
        return APIResponse(
            status="ok",
            message="任务已记录，但管线未初始化",
            data={"task_id": state.id, "status": state.status.value},
        )

    config = pipeline.get_template(template_name)
    if config is None:
        # fallback: 没匹配模板时直接调 planner（兼容旧行为）
        if cap_registry is not None and "planner" in cap_registry:
            asyncio_task = asyncio.create_task(
                _run_single_agent_fallback(state.id, cap_registry, req.requirement, writer)
            )
            _registry.update(state.id, status=TaskStatus.RUNNING)
            _registry.attach(state.id, asyncio_task)
            return APIResponse(
                status="ok",
                message="任务已提交（fallback: 单 Agent 模式）",
                data={"task_id": state.id, "status": state.status.value},
            )

        _registry.mark_done(
            state.id,
            TaskStatus.FAILED,
            error=f"未找到管线模板: {template_name}",
        )
        writer.write("error", {"error": f"未找到管线模板: {template_name}"})
        return APIResponse(
            status="error",
            message=f"未找到管线模板: {template_name}",
            data={"task_id": state.id, "status": state.status.value},
        )

    asyncio_task = asyncio.create_task(
        _run_pipeline_task(state.id, pipeline, config, req.requirement, writer)
    )
    _registry.update(state.id, status=TaskStatus.RUNNING)
    _registry.attach(state.id, asyncio_task)

    return APIResponse(
        status="ok",
        message="任务已提交",
        data={"task_id": state.id, "status": state.status.value},
    )


# ─── 后台执行：Pipeline 路径 ──────────────────────────


async def _run_pipeline_task(
    task_id: str,
    pipeline,
    config,
    requirement: str,
    writer: TranscriptWriter,
) -> None:
    """异步执行 Pipeline 并把进度事件落到 TaskState + transcript。"""

    async def on_step_event(event: Dict[str, Any]) -> None:
        # 写 transcript
        writer.write(str(event.get("type", "step")), event)

        # 更新 progress
        ev_type = event.get("type")
        if ev_type == "step_started":
            _registry.set_progress(
                task_id,
                current_step=event.get("step"),
                activity=f"running step '{event.get('step')}'",
            )
            await broadcast_monitor_event(
                "agent_progress",
                {
                    "task_id": task_id,
                    "agent": event.get("capability") or event.get("agent"),
                    "activity": "planning" if event.get("step") == "plan" else "running",
                    "status": "running",
                    "current_step": event.get("step"),
                },
            )
        elif ev_type in ("step_completed", "step_failed", "step_skipped"):
            # 把中间结果填到 plan / code / review 字段（兼容旧前端）
            step_name = event.get("step")
            output = event.get("output")
            if output:
                fields_map = {"plan": "plan", "code": "code", "review": "review"}
                target = fields_map.get(str(step_name))
                if target:
                    _registry.update(task_id, **{target: output})
            _registry.set_progress(
                task_id,
                activity=f"{ev_type}: {step_name}",
            )
            await broadcast_monitor_event(
                "agent_progress",
                {
                    "task_id": task_id,
                    "activity": "completed" if ev_type == "step_completed" else ev_type,
                    "status": "completed" if ev_type == "step_completed" else "error",
                    "current_step": step_name,
                    "elapsed_ms": event.get("duration_ms"),
                    "error": event.get("error"),
                },
            )

    writer.write("started", {"requirement": requirement})

    parent_token = set_parent_task_id(task_id)
    try:
        result = await pipeline.execute(
            config,
            initial_context={
                "user_requirement": requirement,
                "requirement": requirement,
                "message": requirement,
            },
            on_step_event=on_step_event,
        )

        from core.pipeline import PipelineStatus

        if result.status == PipelineStatus.COMPLETED:
            _registry.mark_done(task_id, TaskStatus.COMPLETED, output=result.context)
            writer.write("done", {"status": "completed", "duration_ms": result.duration_ms})
        else:
            _registry.mark_done(task_id, TaskStatus.FAILED, error=result.error)
            writer.write("done", {"status": "failed", "error": result.error})

    except asyncio.CancelledError:
        _registry.mark_done(task_id, TaskStatus.KILLED, error="cancelled by user")
        writer.write("killed", {})
        raise
    except Exception as exc:
        logger.exception("Task '%s' pipeline failed", task_id)
        _registry.mark_done(task_id, TaskStatus.FAILED, error=str(exc))
        writer.write("error", {"error": str(exc)})
    finally:
        reset_parent_task_id(parent_token)


async def _run_single_agent_fallback(
    task_id: str,
    cap_registry,
    requirement: str,
    writer: TranscriptWriter,
) -> None:
    """fallback: 没匹配模板时，直接调 planner Agent。"""
    writer.write("started", {"mode": "fallback_single_agent"})
    _registry.set_progress(task_id, current_step="planner", activity="single-agent fallback")

    parent_token = set_parent_task_id(task_id)
    try:
        result = await cap_registry.execute("planner", requirement=requirement)
        _registry.mark_done(task_id, TaskStatus.COMPLETED, output=result)
        _registry.update(task_id, plan=result)
        writer.write("done", {"status": "completed"})
    except asyncio.CancelledError:
        _registry.mark_done(task_id, TaskStatus.KILLED, error="cancelled by user")
        writer.write("killed", {})
        raise
    except Exception as exc:
        logger.exception("Task '%s' single-agent fallback failed", task_id)
        _registry.mark_done(task_id, TaskStatus.FAILED, error=str(exc))
        writer.write("error", {"error": str(exc)})
    finally:
        reset_parent_task_id(parent_token)


# ─── 查询 ─────────────────────────────────────────────


@router.get("", response_model=APIResponse)
async def list_tasks():
    """列出所有任务（按创建时间倒序）。"""
    return APIResponse(
        status="ok",
        data=[t.to_dict() for t in _registry.list()],
    )


@router.get("/{task_id}", response_model=APIResponse)
async def get_task(task_id: str):
    """获取任务详情（含 progress 字段）。"""
    state = _registry.get(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return APIResponse(status="ok", data=state.to_dict())


@router.get("/{task_id}/transcript", response_model=APIResponse)
async def get_task_transcript(task_id: str, offset: int = 0):
    """读取任务的事件 transcript（JSONL 解析后的数组）。"""
    if _registry.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return APIResponse(
        status="ok",
        data={
            "task_id": task_id,
            "offset": offset,
            "events": read_transcript(task_id, offset=offset),
        },
    )


# ─── 取消 ─────────────────────────────────────────────


@router.delete("/{task_id}", response_model=APIResponse)
async def cancel_task(task_id: str):
    """取消任务：cancel 后台 asyncio.Task；终态置 KILLED。"""
    if _registry.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    _registry.kill(task_id)
    return APIResponse(
        status="ok",
        message="已请求取消任务",
        data={"task_id": task_id, "status": _registry.get(task_id).status.value},
    )
