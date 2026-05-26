"""Chatroom speaking-task scheduler (Phase 2).

This module wires the static :mod:`core.chatroom` storage to the live
infrastructure: capability registry, task registry, websocket fan-out and the
LLM client used for background summary jobs.

Responsibilities
- ``dispatch_speaking_task`` — schedule a single Agent reply as an
  ``AGENT_SPEAK`` task. It performs membership / depth validation up front,
  inserts a placeholder message, kicks off ``_run_speaking_task`` in the
  background and returns immediately. Relay dispatch is handled inside
  ``_run_speaking_task`` after ``done`` events arrive.
- ``_run_speaking_task`` — drains ``cap.execute_stream`` and rebroadcasts the
  events through ``broadcast_chatroom_event`` so subscribed websockets see
  thinking/tool/done deltas in real time. Also persists every step into the
  task transcript and pushes relay tasks for any mention found in the final
  reply.
- ``maybe_schedule_summary`` — checks ``should_summarize`` and fires a
  background ``summarize_room`` job, broadcasting ``chatroom_summary_updated``
  on success. Failures are swallowed by ``summarize_room`` itself.

The functions are intentionally synchronous from the caller's perspective —
they return immediately after creating the asyncio task. The HTTP endpoint
in ``api/routes/chatrooms.py`` is the only synchronous entry point for now.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .chatroom import (
    ChatroomStore,
    build_room_context,
    parse_mentions,
    should_summarize,
    summarize_room,
)
from .task import (
    TaskRegistry,
    TaskStatus,
    TaskType,
    TranscriptWriter,
    reset_current_create_counter,
    reset_current_room_id,
    reset_current_speaker_name,
    reset_workspace_root_override,
    set_current_create_counter,
    set_current_room_id,
    set_current_speaker_name,
    set_workspace_root_override,
)


logger = logging.getLogger(__name__)


# ─── 依赖适配器 ─────────────────────────────────────────────


def _get_capability_registry():
    """Late binding: routes import order may register cap registry after this module."""

    try:
        from api.dependencies import get_capability_registry  # type: ignore
    except Exception:  # pragma: no cover — defensive
        return None
    return get_capability_registry()


def _get_task_registry() -> Optional[TaskRegistry]:
    try:
        from api.dependencies import get_task_registry  # type: ignore
    except Exception:  # pragma: no cover — defensive
        return None
    return get_task_registry()


def _get_llm_client():
    try:
        from api.dependencies import get_llm_client  # type: ignore
    except Exception:  # pragma: no cover — defensive
        return None
    return get_llm_client()


async def _broadcast(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Best-effort broadcast helper — websocket layer may be absent in tests."""

    try:
        from api.websocket.handlers import broadcast_chatroom_event  # type: ignore
    except Exception:  # pragma: no cover — defensive
        return
    try:
        await broadcast_chatroom_event(room_id, event_type, data)
    except Exception as exc:  # pragma: no cover — fan-out must not crash speakers
        logger.warning("chatroom broadcast failed (%s): %s", event_type, exc)


def _broadcast_async(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Schedule a broadcast without blocking the caller.

    Used by the synchronous public API (``dispatch_speaking_task``) so it can
    notify subscribers without awaiting. When called outside of a running
    event loop (e.g. unit tests) we silently drop the broadcast — the caller
    only relies on it for UX, not correctness.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_broadcast(room_id, event_type, data))


# ─── 工具函数 ───────────────────────────────────────────────


def _all_member_names(room: Dict[str, Any]) -> List[str]:
    members = list(room.get("members") or [])
    dynamic = [m.get("name") for m in (room.get("dynamic_members") or []) if m.get("name")]
    return list(dict.fromkeys([*members, *dynamic]))


def _coerce_response_text(content: Any, fallback: str) -> str:
    """Pick the user-facing text out of a stream's final ``done`` content."""

    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("response", "content", "text", "answer", "message"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if content is None:
        return fallback
    return fallback or str(content)


def _truncate(value: Any, limit: int = 500) -> str:
    """Render any tool result as a short preview string."""

    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            import json

            preview = json.dumps(value, ensure_ascii=False)
        except Exception:  # pragma: no cover
            preview = str(value)
    else:
        preview = str(value)
    if len(preview) > limit:
        return preview[: limit - 1] + "…"
    return preview


def _relay_depth(messages: List[Dict[str, Any]], parent_message_id: Optional[str]) -> int:
    """Walk the parent_message_id chain backwards and count agent hops.

    A user message has depth 0; the first agent reply to that user is depth 1;
    a relay-triggered agent reply to that agent is depth 2; and so on. We stop
    when we hit a user/system message or a missing parent.
    """

    if not parent_message_id:
        return 0

    by_id = {m.get("id"): m for m in messages if m.get("id")}
    depth = 0
    seen: Set[str] = set()
    cursor = parent_message_id
    while cursor and cursor not in seen:
        seen.add(cursor)
        msg = by_id.get(cursor)
        if msg is None:
            break
        sender = str(msg.get("sender") or "")
        if sender.startswith("agent:"):
            depth += 1
        else:
            # 走到 user / system，链路根；不再继续累加
            break
        cursor = msg.get("parent_message_id") or None
    return depth


def _attach_workspace(payload: Dict[str, Any], workspace_id: Optional[str]) -> None:
    """Resolve a managed Project workspace and inject its trusted root.

    If the workspace is unknown we just log a warning and skip — the spec
    says we should not block the run for a missing workspace.
    """

    if not workspace_id:
        return
    try:
        from core.workspace import WorkspaceNotFoundError, WorkspaceStore  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.warning("workspace module unavailable: %s", exc)
        return
    try:
        workspace = WorkspaceStore().get(workspace_id)
    except WorkspaceNotFoundError:
        logger.warning("chatroom workspace not found: %s", workspace_id)
        return
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom workspace lookup failed: %s", exc)
        return
    payload["workspace_id"] = workspace.id
    payload["_trusted_workspace_root"] = workspace.root_path


def _maybe_set_workspace_root(
    room_id: str,
    *,
    store: ChatroomStore,
):
    """Set ``workspace_root_override`` ContextVar from room.workspace_id.

    Returns the contextvar Token (or ``None``) so the caller can reset it
    in a finally block. Logs but never raises when the workspace is missing
    so a stale ``workspace_id`` cannot block the speaker.
    """

    from pathlib import Path

    room = store.get_room(room_id) or {}
    workspace_id = (room.get("workspace_id") or "").strip()
    if not workspace_id:
        return None

    try:
        from core.workspace import WorkspaceNotFoundError, WorkspaceStore  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.warning("workspace module unavailable: %s", exc)
        return None
    try:
        workspace = WorkspaceStore().get(workspace_id)
    except WorkspaceNotFoundError:
        logger.warning(
            "chatroom workspace not found, skipping workspace_root_override: %s",
            workspace_id,
        )
        return None
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom workspace lookup failed: %s", exc)
        return None

    try:
        return set_workspace_root_override(Path(workspace.root_path))
    except Exception as exc:  # pragma: no cover
        logger.warning("set_workspace_root_override failed: %s", exc)
        return None


# ─── 主入口 ────────────────────────────────────────────────


def dispatch_speaking_task(
    room_id: str,
    agent_name: str,
    *,
    prompt: Optional[str] = None,
    parent_message_id: Optional[str] = None,
    store: Optional[ChatroomStore] = None,
) -> Dict[str, Any]:
    """Schedule a single Agent reply for ``room_id``.

    This function never blocks: it validates, allocates the placeholder
    message, registers the task, kicks off the runner with
    ``asyncio.create_task`` and returns the dispatch ticket so callers can
    surface a task_id to the API client immediately.
    """

    target_store = store or ChatroomStore()
    room = target_store.get_room(room_id)
    if not room:
        return {"task_id": None, "message_id": None, "error": "chatroom_not_found"}

    # ── 1) 成员校验 ────────────────────────────────────────
    valid_names = _all_member_names(room)
    if agent_name not in valid_names:
        failed = target_store.add_message(
            room_id,
            {
                "sender": f"agent:{agent_name}",
                "content": f"成员 {agent_name} 不在房间里",
                "status": "failed",
                "parent_message_id": parent_message_id,
                "meta": {"error": "member_not_in_room"},
            },
        )
        _broadcast_async(
            room_id,
            "chatroom_message_failed",
            {"room_id": room_id, "message": failed, "error": "member_not_in_room"},
        )
        return {
            "task_id": None,
            "message_id": (failed or {}).get("id"),
            "error": "member_not_in_room",
            "agent_name": agent_name,
        }

    cap_registry = _get_capability_registry()
    if cap_registry is None or cap_registry.get(agent_name) is None:
        failed = target_store.add_message(
            room_id,
            {
                "sender": f"agent:{agent_name}",
                "content": f"成员 {agent_name} 已失效（capability 未注册）",
                "status": "failed",
                "parent_message_id": parent_message_id,
                "meta": {"error": "agent_not_registered"},
            },
        )
        _broadcast_async(
            room_id,
            "chatroom_message_failed",
            {"room_id": room_id, "message": failed, "error": "agent_not_registered"},
        )
        return {
            "task_id": None,
            "message_id": (failed or {}).get("id"),
            "error": "agent_not_registered",
            "agent_name": agent_name,
        }

    # ── 2) 接力深度护栏 ────────────────────────────────────
    settings = room.get("settings") or {}
    try:
        max_depth = int(settings.get("max_relay_depth", 3))
    except (TypeError, ValueError):
        max_depth = 3

    current_depth = _relay_depth(room.get("messages") or [], parent_message_id)
    if current_depth >= max_depth:
        notice = target_store.add_message(
            room_id,
            {
                "sender": "system",
                "content": f"已达接力上限 {max_depth} 层，忽略 @{agent_name}",
                "status": "done",
                "parent_message_id": parent_message_id,
                "meta": {
                    "error": "max_relay_depth",
                    "max_relay_depth": max_depth,
                    "skipped_agent": agent_name,
                },
            },
        )
        _broadcast_async(
            room_id,
            "chatroom_message_added",
            {"room_id": room_id, "message": notice},
        )
        return {
            "task_id": None,
            "message_id": (notice or {}).get("id"),
            "skipped": "max_relay_depth",
            "agent_name": agent_name,
        }

    # ── 3) 摘要触发（不阻塞）──────────────────────────────
    maybe_schedule_summary(room_id, store=target_store)

    # ── 4) 占位消息 + 注册 task ───────────────────────────
    placeholder = target_store.add_message(
        room_id,
        {
            "sender": f"agent:{agent_name}",
            "content": "",
            "status": "pending",
            "parent_message_id": parent_message_id,
            "meta": {"prompt": prompt or ""},
        },
    )
    if not placeholder:
        return {"task_id": None, "message_id": None, "error": "placeholder_failed"}

    message_id = placeholder["id"]

    task_registry = _get_task_registry()
    if task_registry is None:
        # 没注册 task registry → 仍然把消息标 failed，便于排查
        target_store.update_message(
            room_id,
            message_id,
            content="task registry 未初始化",
            status="failed",
            meta={"error": "task_registry_missing"},
        )
        _broadcast_async(
            room_id,
            "chatroom_message_failed",
            {"room_id": room_id, "message_id": message_id, "error": "task_registry_missing"},
        )
        return {"task_id": None, "message_id": message_id, "error": "task_registry_missing"}

    state = task_registry.create(
        task_type=TaskType.AGENT_SPEAK,
        requirement=prompt or "请发言",
        agent_name=agent_name,
        workspace_id=room.get("workspace_id"),
    )
    task_id = state.id
    target_store.update_message(
        room_id,
        message_id,
        task_id=task_id,
    )

    _broadcast_async(
        room_id,
        "chatroom_message_started",
        {
            "room_id": room_id,
            "task_id": task_id,
            "agent_name": agent_name,
            "message": target_store.get_room(room_id)["messages"][-1] if target_store.get_room(room_id) else None,
        },
    )

    runner = asyncio.create_task(
        _run_speaking_task(
            room_id=room_id,
            message_id=message_id,
            task_id=task_id,
            agent_name=agent_name,
            prompt=prompt,
            parent_message_id=parent_message_id,
            store=target_store,
        )
    )
    try:
        task_registry.attach(task_id, runner)
    except KeyError:
        # registry 在创建后被换掉的极端情况：忽略，runner 仍会自己跑完
        pass

    return {
        "task_id": task_id,
        "message_id": message_id,
        "agent_name": agent_name,
    }


# ─── 摘要调度 ──────────────────────────────────────────────


def maybe_schedule_summary(
    room_id: str,
    *,
    store: Optional[ChatroomStore] = None,
) -> Optional[asyncio.Task]:
    """Fire ``summarize_room`` in the background when the threshold is met.

    Returns the asyncio task on dispatch, ``None`` when no summary is needed
    or required dependencies are missing.
    """

    target_store = store or ChatroomStore()
    room = target_store.get_room(room_id)
    if not room:
        return None
    if not should_summarize(room):
        return None

    llm_client = _get_llm_client()
    if llm_client is None:
        logger.warning("chatroom summary skipped: llm client unavailable")
        return None

    async def _runner() -> None:
        snapshot = target_store.get_room(room_id)
        if not snapshot:
            return
        updated = await summarize_room(snapshot, llm_client, store=target_store)
        if updated is None:
            return
        await _broadcast(
            room_id,
            "chatroom_summary_updated",
            {
                "room_id": room_id,
                "summary": updated.get("summary"),
                "summary_until_msg_id": updated.get("summary_until_msg_id"),
            },
        )

    try:
        return asyncio.create_task(_runner(), name=f"chatroom-summary:{room_id}")
    except RuntimeError:  # pragma: no cover — no running loop in unit calls
        logger.warning("chatroom summary not scheduled: no running loop")
        return None


# ─── Speaking task runner ─────────────────────────────────


async def _run_speaking_task(
    *,
    room_id: str,
    message_id: str,
    task_id: str,
    agent_name: str,
    prompt: Optional[str],
    parent_message_id: Optional[str],
    store: ChatroomStore,
) -> None:
    """Background coroutine that streams an Agent reply into the chatroom.

    Owns the message lifecycle: ``streaming → done | failed`` and writes
    every event into the task transcript so ``GET /api/tasks/{id}/transcript``
    surfaces the full conversation later.
    """

    cap_registry = _get_capability_registry()
    task_registry = _get_task_registry()
    writer = TranscriptWriter(task_id)

    room_token = set_current_room_id(room_id)
    speaker_token = set_current_speaker_name(agent_name)
    create_counter: List[int] = [0]
    counter_token = set_current_create_counter(create_counter)
    workspace_token = _maybe_set_workspace_root(room_id, store=store)
    started_at = datetime.utcnow()
    tool_started: Dict[str, datetime] = {}
    tool_total = 0  # 累计已发起的 tool_call 数（含未完成）
    accumulated = ""
    final_text = ""
    final_meta: Dict[str, Any] = {}

    try:
        if cap_registry is None:
            raise RuntimeError("capability registry not initialised")
        cap = cap_registry.get(agent_name)
        if cap is None:
            raise RuntimeError(f"agent '{agent_name}' not registered")

        # ── streaming 状态切换 ────────────────────────────
        if task_registry is not None:
            task_registry.update(task_id, status=TaskStatus.RUNNING)
        store.update_message(
            room_id,
            message_id,
            status="streaming",
        )
        writer.write(
            "started",
            {
                "kind": "agent_speak",
                "agent_name": agent_name,
                "room_id": room_id,
                "message_id": message_id,
                "parent_message_id": parent_message_id,
            },
        )
        await _broadcast(
            room_id,
            "chatroom_message_added",
            {
                "room_id": room_id,
                "task_id": task_id,
                "message": store.get_room(room_id)["messages"][-1] if store.get_room(room_id) else None,
            },
        )

        # ── 拼上下文 ──────────────────────────────────────
        room_snapshot = store.get_room(room_id) or {}
        context_messages = build_room_context(room_snapshot, agent_name)

        payload: Dict[str, Any] = {
            "messages": context_messages,
            "message": prompt or "请发言",
            "task_id": task_id,
        }
        _attach_workspace(payload, room_snapshot.get("workspace_id"))

        stream_fn = getattr(cap, "execute_stream", None)
        if stream_fn is None:
            # 兜底：非流式 capability 直接 execute
            result = await cap.execute(**payload)
            final_text = _coerce_response_text(result, fallback=prompt or "")
            if isinstance(result, dict):
                for key in ("usage", "elapsed_ms", "metrics"):
                    if key in result:
                        final_meta[key] = result[key]
        else:
            async for event in stream_fn(**payload):
                etype = str(event.get("type") or "")

                if etype == "thinking":
                    chunk = str(event.get("content") or "")
                    accumulated += chunk
                    writer.write("step_thinking", {"content": chunk})
                    await _broadcast(
                        room_id,
                        "chatroom_agent_thinking",
                        {
                            "room_id": room_id,
                            "task_id": task_id,
                            "message_id": message_id,
                            "delta": chunk,
                        },
                    )

                elif etype == "tool_call":
                    tool_name = str(event.get("tool") or "")
                    call_id = str(event.get("tool_call_id") or f"{tool_name}:{len(tool_started) + 1}")
                    tool_started[call_id] = datetime.utcnow()
                    tool_total += 1
                    writer.write(
                        "step_tool_call",
                        {
                            "tool": tool_name,
                            "tool_call_id": call_id,
                            "args": event.get("args"),
                        },
                    )
                    await _broadcast(
                        room_id,
                        "chatroom_tool_call",
                        {
                            "room_id": room_id,
                            "task_id": task_id,
                            "message_id": message_id,
                            "tool_name": tool_name,
                            "args": event.get("args"),
                            "tool_call_id": call_id,
                        },
                    )

                elif etype == "tool_result":
                    tool_name = str(event.get("tool") or "")
                    call_id = str(event.get("tool_call_id") or f"{tool_name}:latest")
                    started_tool = tool_started.pop(call_id, None)
                    elapsed_ms = (
                        round((datetime.utcnow() - started_tool).total_seconds() * 1000, 2)
                        if started_tool
                        else None
                    )
                    raw_result = event.get("result")
                    is_error = isinstance(raw_result, dict) and bool(raw_result.get("error"))
                    preview = _truncate(raw_result, limit=500)
                    writer.write(
                        "step_tool_result",
                        {
                            "tool": tool_name,
                            "tool_call_id": call_id,
                            "result_preview": preview,
                            "elapsed_ms": elapsed_ms,
                            "status": "error" if is_error else "success",
                        },
                    )
                    await _broadcast(
                        room_id,
                        "chatroom_tool_result",
                        {
                            "room_id": room_id,
                            "task_id": task_id,
                            "message_id": message_id,
                            "tool_name": tool_name,
                            "tool_call_id": call_id,
                            "result_preview": preview,
                            "elapsed_ms": elapsed_ms,
                            "status": "error" if is_error else "success",
                        },
                    )

                elif etype == "done":
                    content = event.get("content")
                    final_text = _coerce_response_text(content, fallback=accumulated)
                    if event.get("usage"):
                        final_meta["usage"] = event["usage"]
                    if event.get("elapsed_ms") is not None:
                        final_meta["elapsed_ms"] = event["elapsed_ms"]
                    final_meta["tool_count"] = tool_total
                    break

                else:
                    # 其余事件类型透传到 transcript，方便排查
                    writer.write(f"step_{etype}", event)

        # ── 完成处理 ──────────────────────────────────────
        if not final_text:
            final_text = accumulated or ""

        all_members = _all_member_names(store.get_room(room_id) or {})
        mentions = parse_mentions(final_text, [n for n in all_members if n != agent_name])
        elapsed_ms = round(
            (datetime.utcnow() - started_at).total_seconds() * 1000,
            2,
        )
        final_meta.setdefault("elapsed_ms", elapsed_ms)
        final_meta["mentions"] = mentions

        store.update_message(
            room_id,
            message_id,
            content=final_text,
            mentions=mentions,
            status="done",
            meta=final_meta,
        )
        writer.write(
            "done",
            {
                "content": final_text,
                "mentions": mentions,
                "elapsed_ms": final_meta.get("elapsed_ms"),
                "usage": final_meta.get("usage"),
            },
        )
        if task_registry is not None:
            task_registry.mark_done(
                task_id,
                TaskStatus.COMPLETED,
                output={"content": final_text, "mentions": mentions},
            )

        room_after = store.get_room(room_id) or {}
        message_after = next(
            (m for m in (room_after.get("messages") or []) if m.get("id") == message_id),
            None,
        )
        await _broadcast(
            room_id,
            "chatroom_message_done",
            {
                "room_id": room_id,
                "task_id": task_id,
                "message": message_after,
                "mentions": mentions,
            },
        )

        # ── 接力派发 ──────────────────────────────────────
        # host_directive 优先：如果发言者是 auto_host 模式下的 host_agent，
        # 优先尝试把回复解析为结构化指令，按指令派发；否则回退到 mention 接力。
        directive_actions = _parse_host_directive(
            final_text,
            room_after,
            speaker=agent_name,
        )
        if directive_actions:
            await _broadcast(
                room_id,
                "chatroom_host_directive",
                {
                    "room_id": room_id,
                    "host": agent_name,
                    "actions": directive_actions,
                },
            )
            for action in directive_actions:
                dispatch_speaking_task(
                    room_id,
                    action["agent"],
                    prompt=action.get("prompt"),
                    parent_message_id=message_id,
                    store=store,
                )
        elif mentions:
            for relay_target in mentions:
                dispatch_speaking_task(
                    room_id,
                    relay_target,
                    parent_message_id=message_id,
                    store=store,
                )

    except asyncio.CancelledError:
        store.update_message(
            room_id,
            message_id,
            content=accumulated + "\n\n[已取消]" if accumulated else "[已取消]",
            status="failed",
            meta={"error": "cancelled"},
        )
        writer.write("killed", {"reason": "cancelled"})
        if task_registry is not None:
            task_registry.mark_done(task_id, TaskStatus.KILLED, error="cancelled by user")
        await _broadcast(
            room_id,
            "chatroom_message_failed",
            {
                "room_id": room_id,
                "task_id": task_id,
                "message_id": message_id,
                "error": "cancelled",
            },
        )
        raise
    except Exception as exc:  # noqa: BLE001 — 兜底
        logger.exception("chatroom speaking task failed for room=%s task=%s", room_id, task_id)
        message = f"调用失败：{exc}"
        store.update_message(
            room_id,
            message_id,
            content=message,
            status="failed",
            meta={"error": str(exc), "exception_type": type(exc).__name__},
        )
        writer.write("error", {"error": str(exc), "exception_type": type(exc).__name__})
        if task_registry is not None:
            task_registry.mark_done(task_id, TaskStatus.FAILED, error=str(exc))
        await _broadcast(
            room_id,
            "chatroom_message_failed",
            {
                "room_id": room_id,
                "task_id": task_id,
                "message_id": message_id,
                "error": str(exc),
            },
        )
    finally:
        if workspace_token is not None:
            reset_workspace_root_override(workspace_token)
        reset_current_create_counter(counter_token)
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)


__all__ = [
    "dispatch_speaking_task",
    "maybe_schedule_summary",
]


# ─── host_directive 解析 ──────────────────────────────────


def _parse_host_directive(
    final_text: str,
    room: Dict[str, Any],
    *,
    speaker: str,
) -> Optional[List[Dict[str, Any]]]:
    """从主持人 Agent 的回复里解析结构化调度指令。

    仅当：(a) 房间 auto_host=True，(b) speaker 与 settings.host_agent 一致，
    (c) 文本里能找到一段可解析的 JSON ``{"actions":[{"agent":...,"prompt":...}]}``，
    才返回 actions 列表（每项已校验 agent 在房间成员里）。
    其余情况返回 None，调用方回退到 mention 解析。
    """

    if not final_text:
        return None
    settings = room.get("settings") or {}
    if not bool(settings.get("auto_host")):
        return None
    host_agent = str(settings.get("host_agent") or "").strip()
    if not host_agent or speaker != host_agent:
        return None

    payload = _extract_json_object(final_text)
    if not isinstance(payload, dict):
        return None
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return None

    valid_names = set(_all_member_names(room)) - {speaker}
    cleaned: List[Dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, dict):
            continue
        agent_name = str(raw.get("agent") or "").strip()
        if not agent_name or agent_name not in valid_names:
            continue
        prompt = raw.get("prompt")
        if prompt is not None and not isinstance(prompt, str):
            prompt = str(prompt)
        cleaned.append({"agent": agent_name, "prompt": prompt})
    return cleaned or None


def _extract_json_object(text: str) -> Optional[Any]:
    """从一段自由文本里抽出第一个完整 JSON 对象。

    优先匹配 ``json``/`json` 代码围栏，其次扫描首个 ``{`` 起到平衡的 ``}``。
    出错全部静默返回 None，让调用方回退。
    """

    # 1) 围栏块 ```json ... ```
    fence = re.search(
        r"```(?:json)?\s*([\s\S]+?)\s*```",
        text,
        flags=re.IGNORECASE,
    )
    if fence:
        try:
            return json.loads(fence.group(1))
        except (ValueError, TypeError):
            pass

    # 2) 首个 { 起的平衡块（朴素括号配对，能处理嵌套）
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except (ValueError, TypeError):
                    return None
    return None
