"""任务与 Agent Run 管理路由。

端点:
- POST   /api/tasks                       — 提交新任务（创建 Agent Run）
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
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from ..schemas import APIResponse, AgentRunCreateRequest, RunControlRequest, TaskSubmitRequest
from ..dependencies import get_capability_registry, get_memory_retriever
from ..websocket.handlers import broadcast_monitor_event
from core.chat_history import ChatHistoryStore
from core.config import load_single_yaml
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
from core.workspace import (
    WorkspaceNotFoundError,
    WorkspaceStore,
    session_workspace_id,
    session_workspace_root,
    workspace_path,
)

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
    """Resolve the effective workspace root for a run instance.

    A managed Project workspace selected by the user wins over the automatic
    run workspace. Unknown ids keep the historical isolated run directory.
    """

    safe_id = _safe_instance_id(workspace_id, fallback="default")
    if safe_id.startswith("session-"):
        return session_workspace_root(safe_id.removeprefix("session-"))
    try:
        managed = WorkspaceStore().get(safe_id)
        if managed.kind == "project":
            return Path(managed.root_path).resolve()
    except WorkspaceNotFoundError:
        pass

    return workspace_path("runs", safe_id, create=True)


def _session_workspace_id(session_id: Optional[str]) -> Optional[str]:
    if not session_id:
        return None
    session = ChatHistoryStore().get_session(session_id)
    if not session:
        return None
    value = str(session.get("workspace_id") or "").strip()
    return value or None


def _agent_default_workspace_id(agent_name: str) -> Optional[str]:
    data = load_single_yaml("agents.yaml")
    agents = data.get("agents", [])
    if not isinstance(agents, list):
        return None
    for agent in agents:
        if not isinstance(agent, dict) or agent.get("name") != agent_name:
            continue
        value = str(agent.get("default_workspace_id") or agent.get("workspace_id") or "").strip()
        return value or None
    return None


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
            max_iterations=req.max_iterations,
            completion_criteria=req.completion_criteria,
            auto_memory=req.auto_memory,
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
        max_iterations=req.max_iterations,
        completion_criteria=req.completion_criteria,
        auto_memory=req.auto_memory,
        parent_id=req.parent_id,
    )
    requested_workspace_id = (
        req.workspace_id
        or _session_workspace_id(req.session_id)
        or (session_workspace_id(req.session_id) if req.session_id else None)
        or _agent_default_workspace_id(agent_name)
    )
    fallback_workspace_id = (
        f"run-{provisional.id[:8]}"
    )
    workspace_id = _safe_instance_id(requested_workspace_id, fallback=fallback_workspace_id)
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
            "max_iterations": req.max_iterations,
            "completion_criteria": req.completion_criteria,
            "auto_memory": req.auto_memory,
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
    """提交新任务，始终创建 Agent Run。"""
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
    state = _registry.get(task_id)

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
            "_trusted_workspace_root": str(workspace_root),
            "max_iterations": state.max_iterations if state else 50,
            "completion_criteria": state.completion_criteria if state else "",
            "auto_memory": state.auto_memory if state else True,
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
        await broadcast_monitor_event(
            "agent_progress",
            {
                "run_id": task_id,
                "task_id": task_id,
                "agent": agent_name,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "activity": "agent_loop",
                "status": "running",
                "current_step": "agent_loop",
            },
        )

        stream_fn = getattr(agent_cap, "execute_stream", None)
        if callable(stream_fn):
            async for event in stream_fn(**payload):
                ev_type = str(event.get("type") or "event")
                writer.write(ev_type, event)

                if ev_type == "thinking":
                    _registry.set_progress(task_id, activity="thinking")
                    await broadcast_monitor_event(
                        "agent_progress",
                        {
                            "run_id": task_id,
                            "task_id": task_id,
                            "agent": agent_name,
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "activity": "thinking",
                            "status": "running",
                            "current_step": "agent_loop",
                        },
                    )
                elif ev_type == "tool_call":
                    _registry.set_progress(
                        task_id,
                        activity=f"calling tool {event.get('tool')}",
                        last_tool=event.get("tool"),
                        current_step="tool_use",
                    )
                    await broadcast_monitor_event(
                        "agent_progress",
                        {
                            "run_id": task_id,
                            "task_id": task_id,
                            "agent": agent_name,
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "activity": "calling_tool",
                            "status": "running",
                            "tool": event.get("tool"),
                            "tool_call_id": event.get("tool_call_id"),
                            "current_step": "tool_use",
                        },
                    )
                elif ev_type == "tool_result":
                    result_payload = event.get("result")
                    is_error = isinstance(result_payload, dict) and bool(result_payload.get("error"))
                    _registry.set_progress(
                        task_id,
                        tool_count=1,
                        activity=f"tool result {event.get('tool')}",
                        last_tool=event.get("tool"),
                    )
                    await broadcast_monitor_event(
                        "agent_progress",
                        {
                            "run_id": task_id,
                            "task_id": task_id,
                            "agent": agent_name,
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "activity": "tool_result",
                            "status": "error" if is_error else "running",
                            "tool": event.get("tool"),
                            "tool_call_id": event.get("tool_call_id"),
                            "current_step": "tool_use",
                        },
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
            await broadcast_monitor_event(
                "agent_progress",
                {
                    "run_id": task_id,
                    "task_id": task_id,
                    "agent": agent_name,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "activity": "running",
                    "status": "running",
                },
            )
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
        await broadcast_monitor_event(
            "agent_progress",
            {
                "run_id": task_id,
                "task_id": task_id,
                "agent": agent_name,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "activity": "completed" if status == "completed" else "failed",
                "status": status,
                "duration_ms": int((asyncio.get_event_loop().time() - started) * 1000),
                "error": failed_error,
            },
        )

    except asyncio.CancelledError:
        _registry.mark_done(task_id, TaskStatus.KILLED, error="cancelled by user")
        writer.write("killed", {})
        await broadcast_monitor_event(
            "agent_run_cancelled",
            {"run_id": task_id, "task_id": task_id, "agent": agent_name, "status": "killed"},
        )
        await broadcast_monitor_event(
            "agent_progress",
            {"run_id": task_id, "task_id": task_id, "agent": agent_name, "activity": "cancelled", "status": "killed"},
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
        await broadcast_monitor_event(
            "agent_progress",
            {"run_id": task_id, "task_id": task_id, "agent": agent_name, "activity": "failed", "status": "failed", "error": str(exc)},
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
    if req.action == "pause":
        if not _registry.pause(run_id):
            return APIResponse(status="error", message="当前运行不可暂停")
        writer = TranscriptWriter(run_id)
        writer.write("paused", {"reason": "user_control"})
        return APIResponse(status="ok", message="运行已暂停", data=_registry.get(run_id).to_dict())
    if req.action == "resume":
        if not _registry.resume(run_id):
            return APIResponse(status="error", message="当前运行不可继续")
        writer = TranscriptWriter(run_id)
        writer.write("resumed", {"reason": "user_control"})
        return APIResponse(status="ok", message="运行已继续", data=_registry.get(run_id).to_dict())
    return APIResponse(status="error", message=f"不支持的控制动作: {req.action}")


@runs_router.get("/{run_id}/memory-context", response_model=APIResponse)
async def get_run_memory_context(run_id: str, max_results: int = 6):
    """Return memories that would orient this run."""

    state = _registry.get(run_id)
    if state is None or state.type is not TaskType.AGENT_RUN:
        raise HTTPException(status_code=404, detail="运行不存在")

    retriever = get_memory_retriever()
    if retriever is None:
        return APIResponse(
            status="ok",
            data={
                "run_id": run_id,
                "query": state.requirement,
                "completion_criteria": state.completion_criteria,
                "auto_memory": state.auto_memory,
                "memories": [],
                "note": "记忆检索器未初始化",
            },
        )

    scored = await retriever.retrieve_with_scores(
        context=state.requirement,
        max_results=max(1, min(max_results, 20)),
    )
    memories = []
    for item in scored:
        memory = item["memory"]
        payload = memory.to_dict()
        payload["retrieval"] = item.get("retrieval", {})
        memories.append(payload)

    return APIResponse(
        status="ok",
        data={
            "run_id": run_id,
            "query": state.requirement,
            "completion_criteria": state.completion_criteria,
            "auto_memory": state.auto_memory,
            "memories": memories,
        },
    )


@runs_router.delete("/{run_id}", response_model=APIResponse)
async def cancel_run(run_id: str):
    state = _registry.get(run_id)
    if state is None or state.type is not TaskType.AGENT_RUN:
        raise HTTPException(status_code=404, detail="运行不存在")
    _registry.kill(run_id)
    return APIResponse(status="ok", message="已请求取消运行", data=state.to_dict())
