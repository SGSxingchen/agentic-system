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
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from ..schemas import APIResponse, AgentRunCreateRequest, RunControlRequest, TaskSubmitRequest
from ..dependencies import get_capability_registry, get_pipeline
from ..websocket.handlers import broadcast_monitor_event
from core.task import (
    TaskRegistry,
    TaskStatus,
    TaskType,
    TranscriptWriter,
    read_transcript,
    reset_parent_task_id,
    reset_workspace_root_override,
    set_parent_task_id,
    set_workspace_root_override,
    transcript_path,
)
from core.workspace import workspace_path

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
runs_router = APIRouter(prefix="/api/runs", tags=["runs"])

logger = logging.getLogger(__name__)

# 进程内单例：所有任务的注册中心
_registry = TaskRegistry()


def get_task_registry() -> TaskRegistry:
    """暴露给测试与其他模块使用。"""
    return _registry


def _terminal_statuses() -> set[TaskStatus]:
    return {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED}


def _safe_instance_id(value: Optional[str], *, fallback: str) -> str:
    """Return a path-safe instance identifier for workspace/session-style IDs."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-_")
    return cleaned[:80] or fallback


def _run_workspace(workspace_id: str):
    """Resolve an isolated mutable workspace path for a run instance."""
    safe_id = _safe_instance_id(workspace_id, fallback="default")
    return workspace_path("runs", safe_id, create=True)


async def _create_agent_run(req: AgentRunCreateRequest, *, compat_task: bool = False) -> APIResponse:
    """Create and start an autonomous Agent Run.

    This is the new default scheduler path: it does not load a step template and
    does not assume plan→code→review. The selected Agent receives the goal,
    run/session/workspace identifiers and tool feedback; the Agent's own
    tool-use loop decides the next action.
    """

    cap_registry = get_capability_registry()
    if cap_registry is None:
        return APIResponse(status="error", message="Capability registry 未初始化")

    agent_name = (req.agent_name or "assistant").strip() or "assistant"
    agent_cap = cap_registry.get(agent_name)
    if agent_cap is None and compat_task:
        # /api/tasks auto is a migration compatibility layer: keep returning a
        # durable task record instead of failing the old submit flow outright.
        failed = _registry.create(
            task_type=TaskType.AGENT_RUN,
            requirement=req.goal,
            agent_name=agent_name,
            session_id=req.session_id,
            workspace_id=_safe_instance_id(req.workspace_id, fallback="unassigned"),
            mode=req.mode or "autonomous",
            strategy=req.strategy or "agent_decides",
            parent_id=req.parent_id,
        )
        failed.output_file = str(transcript_path(failed.id))
        writer = TranscriptWriter(failed.id)
        error = f"Agent/Capability 不存在: {agent_name}"
        writer.write("created", {"kind": "agent_run", "goal": req.goal, "agent_name": agent_name})
        writer.write("error", {"error": error})
        _registry.mark_done(failed.id, TaskStatus.FAILED, error=error)
        return APIResponse(status="ok", message="任务已记录，但 Agent 未初始化", data=failed.to_dict())
    if agent_cap is None:
        return APIResponse(status="error", message=f"Agent/Capability 不存在: {agent_name}")

    # Allocate a state first so we can derive a stable workspace when omitted.
    provisional = _registry.create(
        task_type=TaskType.AGENT_RUN,
        requirement=req.goal,
        agent_name=agent_name,
        session_id=req.session_id,
        workspace_id=req.workspace_id,
        mode=req.mode or "autonomous",
        strategy=req.strategy or "agent_decides",
        parent_id=req.parent_id,
    )
    workspace_id = _safe_instance_id(req.workspace_id, fallback=f"run-{provisional.id[:8]}")
    _registry.update(provisional.id, workspace_id=workspace_id)
    provisional.output_file = str(transcript_path(provisional.id))

    writer = TranscriptWriter(provisional.id)
    writer.write(
        "created",
        {
            "kind": "agent_run",
            "goal": req.goal,
            "agent_name": agent_name,
            "session_id": req.session_id,
            "workspace_id": workspace_id,
            "mode": req.mode,
            "strategy": req.strategy,
            "compat_task": compat_task,
        },
    )

    asyncio_task = asyncio.create_task(
        _run_agent_task(
            provisional.id,
            agent_cap,
            agent_name,
            req.goal,
            workspace_id,
            req.session_id,
            req.input or {},
            writer,
        )
    )
    _registry.update(provisional.id, status=TaskStatus.RUNNING)
    _registry.attach(provisional.id, asyncio_task)

    await broadcast_monitor_event(
        "agent_run_started",
        {
            "run_id": provisional.id,
            "task_id": provisional.id,
            "agent": agent_name,
            "workspace_id": workspace_id,
            "session_id": req.session_id,
            "goal": req.goal,
            "status": "running",
        },
    )

    return APIResponse(
        status="ok",
        message="Agent Run 已创建" if not compat_task else "任务已提交（auto→Agent Run 兼容模式）",
        data=provisional.to_dict(),
    )


# ─── 提交 ─────────────────────────────────────────────


@router.post("", response_model=APIResponse)
async def submit_task(req: TaskSubmitRequest):
    """提交新任务。

    兼容迁移策略：
    - pipeline=auto（默认）→ 创建新的自主 Agent Run，不再套固定流水线；
    - pipeline!=auto → 保留旧 Pipeline 模板执行路径，给已有客户端迁移窗口。
    """
    if req.pipeline == "auto":
        return await _create_agent_run(
            AgentRunCreateRequest(
                goal=req.requirement,
                agent_name=req.agent_name or "assistant",
                session_id=req.session_id,
                workspace_id=req.workspace_id,
                mode="autonomous",
                strategy="agent_decides",
                input=req.input or {},
            ),
            compat_task=True,
        )

    pipeline = get_pipeline()
    cap_registry = get_capability_registry()

    template_name = req.pipeline

    state = _registry.create(
        task_type=TaskType.PIPELINE,
        requirement=req.requirement,
        pipeline_name=template_name,
        mode="compat_pipeline",
        strategy="fixed_template",
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
            data=state.to_dict(),
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
                data=state.to_dict(),
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
            data=state.to_dict(),
        )

    asyncio_task = asyncio.create_task(
        _run_pipeline_task(state.id, pipeline, config, req.requirement, writer)
    )
    _registry.update(state.id, status=TaskStatus.RUNNING)
    _registry.attach(state.id, asyncio_task)

    return APIResponse(
        status="ok",
        message="任务已提交（旧 Pipeline 兼容模式）",
        data=state.to_dict(),
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



async def _run_agent_task(
    task_id: str,
    agent_cap,
    agent_name: str,
    goal: str,
    workspace_id: str,
    session_id: Optional[str],
    input_data: Dict[str, Any],
    writer: TranscriptWriter,
) -> None:
    """Run one autonomous Agent instance and persist its event stream."""

    workspace_root = _run_workspace(workspace_id)
    parent_token = set_parent_task_id(task_id)
    workspace_token = set_workspace_root_override(workspace_root)
    started = asyncio.get_event_loop().time()
    final_output: Any = None
    failed_error: Optional[str] = None

    payload = dict(input_data or {})
    payload.update(
        {
            "message": goal,
            "goal": goal,
            "run_id": task_id,
            "task_id": task_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "workspace_root": str(workspace_root),
        }
    )

    try:
        writer.write(
            "started",
            {
                "kind": "agent_run",
                "agent_name": agent_name,
                "workspace_root": str(workspace_root),
            },
        )
        _registry.set_progress(task_id, current_step="agent_loop", activity="agent deciding next action")

        stream_fn = getattr(agent_cap, "execute_stream", None)
        if callable(stream_fn):
            async for event in stream_fn(**payload):
                ev_type = str(event.get("type") or "event")
                writer.write(ev_type, event)

                if ev_type == "thinking":
                    _registry.set_progress(task_id, activity="thinking")
                elif ev_type == "tool_call":
                    _registry.set_progress(
                        task_id,
                        activity=f"calling tool {event.get('tool')}",
                        last_tool=event.get("tool"),
                        current_step="tool_use",
                    )
                elif ev_type == "tool_result":
                    _registry.set_progress(
                        task_id,
                        tool_count=1,
                        activity=f"tool result {event.get('tool')}",
                        last_tool=event.get("tool"),
                    )
                elif ev_type == "done":
                    final_output = event.get("content")
                    usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                    total_tokens = int(usage.get("total_tokens") or 0)
                    if total_tokens:
                        _registry.set_progress(task_id, total_tokens=total_tokens)
                    if isinstance(final_output, dict) and final_output.get("error"):
                        failed_error = str(final_output.get("error"))
                    break

                await broadcast_monitor_event(
                    "agent_run_event",
                    {
                        "run_id": task_id,
                        "task_id": task_id,
                        "agent": agent_name,
                        "workspace_id": workspace_id,
                        "event_type": ev_type,
                        "tool": event.get("tool"),
                        "status": "running",
                    },
                )
        else:
            # Non-streaming capability fallback. The capability still decides internally;
            # we simply lose incremental visibility.
            final_output = await agent_cap.execute(**payload)
            writer.write("done", {"content": final_output})

        if failed_error:
            _registry.mark_done(task_id, TaskStatus.FAILED, output=final_output, error=failed_error)
            writer.write("error", {"error": failed_error})
            status = "failed"
        else:
            _registry.mark_done(task_id, TaskStatus.COMPLETED, output=final_output)
            status = "completed"

        await broadcast_monitor_event(
            "agent_run_completed",
            {
                "run_id": task_id,
                "task_id": task_id,
                "agent": agent_name,
                "workspace_id": workspace_id,
                "status": status,
                "duration_ms": int((asyncio.get_event_loop().time() - started) * 1000),
            },
        )

    except asyncio.CancelledError:
        _registry.mark_done(task_id, TaskStatus.KILLED, error="cancelled by user")
        writer.write("killed", {})
        await broadcast_monitor_event(
            "agent_run_cancelled",
            {"run_id": task_id, "task_id": task_id, "agent": agent_name, "status": "killed"},
        )
        raise
    except Exception as exc:
        logger.exception("Agent run '%s' failed", task_id)
        _registry.mark_done(task_id, TaskStatus.FAILED, error=str(exc))
        writer.write("error", {"error": str(exc)})
        await broadcast_monitor_event(
            "agent_run_failed",
            {"run_id": task_id, "task_id": task_id, "agent": agent_name, "status": "failed", "error": str(exc)},
        )
    finally:
        reset_workspace_root_override(workspace_token)
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


# ─── Agent Run API（新模型）────────────────────────────


@runs_router.post("", response_model=APIResponse)
async def create_run(req: AgentRunCreateRequest):
    """创建一个新的 Agent Run 实例。"""
    return await _create_agent_run(req)


@runs_router.get("", response_model=APIResponse)
async def list_runs(
    agent_name: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    """列出多个并行 Agent Run，可按 agent/session/workspace/status 过滤。"""
    runs = [t for t in _registry.list() if t.type is TaskType.AGENT_RUN]
    if agent_name:
        runs = [t for t in runs if t.agent_name == agent_name]
    if workspace_id:
        runs = [t for t in runs if t.workspace_id == workspace_id]
    if session_id:
        runs = [t for t in runs if t.session_id == session_id]
    if status:
        runs = [t for t in runs if t.status.value == status]
    return APIResponse(status="ok", data=[t.to_dict() for t in runs])


@runs_router.get("/workspaces", response_model=APIResponse)
async def list_run_workspaces():
    """按 workspace_id 汇总当前进程中的 run 实例。"""
    grouped: Dict[str, Dict[str, Any]] = {}
    for run in [t for t in _registry.list() if t.type is TaskType.AGENT_RUN]:
        workspace_id = run.workspace_id or "default"
        item = grouped.setdefault(
            workspace_id,
            {
                "workspace_id": workspace_id,
                "path": str(_run_workspace(workspace_id)),
                "runs": 0,
                "active_runs": 0,
                "latest_updated_at": run.updated_at,
                "agents": set(),
            },
        )
        item["runs"] += 1
        if run.status not in _terminal_statuses():
            item["active_runs"] += 1
        if run.agent_name:
            item["agents"].add(run.agent_name)
        if run.updated_at > item["latest_updated_at"]:
            item["latest_updated_at"] = run.updated_at

    payload = []
    for item in grouped.values():
        item = dict(item)
        item["agents"] = sorted(item["agents"])
        payload.append(item)
    payload.sort(key=lambda x: x["latest_updated_at"], reverse=True)
    return APIResponse(status="ok", data=payload)


@runs_router.get("/{run_id}", response_model=APIResponse)
async def get_run(run_id: str):
    state = _registry.get(run_id)
    if state is None or state.type is not TaskType.AGENT_RUN:
        raise HTTPException(status_code=404, detail="运行不存在")
    return APIResponse(status="ok", data=state.to_dict())


@runs_router.get("/{run_id}/events", response_model=APIResponse)
async def get_run_events(run_id: str, offset: int = 0):
    state = _registry.get(run_id)
    if state is None or state.type is not TaskType.AGENT_RUN:
        raise HTTPException(status_code=404, detail="运行不存在")
    return APIResponse(
        status="ok",
        data={"run_id": run_id, "offset": offset, "events": read_transcript(run_id, offset=offset)},
    )


@runs_router.post("/{run_id}/control", response_model=APIResponse)
async def control_run(run_id: str, req: RunControlRequest):
    state = _registry.get(run_id)
    if state is None or state.type is not TaskType.AGENT_RUN:
        raise HTTPException(status_code=404, detail="运行不存在")
    if req.action == "cancel":
        _registry.kill(run_id)
        return APIResponse(status="ok", message="已请求取消运行", data=state.to_dict())
    return APIResponse(status="error", message=f"不支持的控制动作: {req.action}")


@runs_router.delete("/{run_id}", response_model=APIResponse)
async def cancel_run(run_id: str):
    state = _registry.get(run_id)
    if state is None or state.type is not TaskType.AGENT_RUN:
        raise HTTPException(status_code=404, detail="运行不存在")
    _registry.kill(run_id)
    return APIResponse(status="ok", message="已请求取消运行", data=state.to_dict())
