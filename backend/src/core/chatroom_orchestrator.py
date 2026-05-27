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
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .chatroom import (
    ChatroomStore,
    build_room_context,
    parse_mentions,
    should_summarize,
    summarize_room,
)
from .chatroom_reminders import build_system_reminders
from .task import (
    TaskRegistry,
    TaskStatus,
    TaskType,
    TranscriptWriter,
    reset_current_create_counter,
    reset_current_parent_message_id,
    reset_current_room_id,
    reset_current_speaker_name,
    reset_workspace_root_override,
    set_current_create_counter,
    set_current_parent_message_id,
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


def _build_memory_query(room: Dict[str, Any], prompt: Optional[str]) -> str:
    """拼接最近 3 条房间消息（任意 sender）+ prompt 作为记忆检索 query。

    与 ChatPanel 单 query 相比，房间多人接力时单条消息上下文太薄；取最近 3 条
    保证检索的语义粒度。done/streaming/pending 都计入——记忆系统自己不在乎完成度。
    """
    messages = room.get("messages") or []
    tail = messages[-3:]
    parts: List[str] = []
    for msg in tail:
        sender = str(msg.get("sender") or "")
        text = str(msg.get("content") or "").strip()
        if not text:
            continue
        parts.append(f"[{sender}] {text}")
    if prompt and prompt.strip():
        parts.append(prompt.strip())
    return "\n".join(parts)


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


def _attach_chatroom_attachment_context(
    payload: Dict[str, Any], room_snapshot: Dict[str, Any]
) -> None:
    """B1 Plan 3 P3 Task 25 — chat room 非图片附件挂入工作区 + system reminder.

    Picks the most recent user-authored message that carries ``attachments``
    (in case earlier @-mentions trail the user one), materializes each
    non-image file under ``<workspace_root>/.attachments/<id>/<name>`` and
    drops the resulting ``<attached_files>`` block into ``attachment_context``
    on the payload. ``Agent.run`` will append it to the system prompt.

    No-op when the workspace root or store cannot be resolved — failure here
    must not block the speak task.
    """

    workspace_root = payload.get("_trusted_workspace_root")
    if not workspace_root:
        return

    messages = room_snapshot.get("messages") or []
    attachment_ids: list[str] = []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("sender") or "").strip() != "user":
            continue
        ids = msg.get("attachments")
        if isinstance(ids, list) and ids:
            attachment_ids = [str(i) for i in ids if i]
            break

    if not attachment_ids:
        return

    try:
        from core.attachment_message_context import (
            build_attachment_reminder,
            get_default_attachment_store,
        )
    except Exception:  # pragma: no cover — defensive
        return

    store = get_default_attachment_store()
    if store is None:
        return
    try:
        block = build_attachment_reminder(
            attachment_ids=attachment_ids,
            workspace_root=workspace_root,
            store=store,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("attachment reminder build failed: %s", exc)
        return
    if block:
        existing = str(payload.get("attachment_context") or "")
        payload["attachment_context"] = (
            f"{existing}\n\n{block}".strip() if existing else block
        )


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
    # Spec 2 §5 / Task 9 — 暴露当前发言占位 message_id；chatroom_dispatch 等
    # 工具读它作为 child speaking task 的 parent_message_id。
    parent_token = set_current_parent_message_id(message_id)
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
        # build_room_context 已在 system 块里嵌入 CHATROOM_COLLABORATION_PROTOCOL，
        # 不再额外强插旧版 _CHATROOM_OVERRIDE_PROMPT（Spec 2 §6 / Task 4）。
        room_snapshot = store.get_room(room_id) or {}
        context_messages = build_room_context(room_snapshot, agent_name)

        # Spec 2 §8 / Task 13 — 在 history 末尾追加 <system-reminder> user 消息，
        # 把 goal 变化 / 新成员 / 你被 @ 等"鲜活"信号塞给 LM；不污染稳定的
        # system 块（cache 友好）。
        try:
            reminder_text = build_system_reminders(
                room_snapshot,
                target_agent=agent_name,
                parent_message_id=parent_message_id,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("build_system_reminders failed: %s", exc)
            reminder_text = ""
        if reminder_text:
            context_messages.append(
                {
                    "role": "user",
                    "content": f"<system-reminder>\n{reminder_text}\n</system-reminder>",
                }
            )
            await _broadcast(
                room_id,
                "chatroom_system_reminder",
                {
                    "room_id": room_id,
                    "task_id": task_id,
                    "agent_name": agent_name,
                    "reminders": [
                        line for line in reminder_text.split("\n") if line.strip()
                    ],
                },
            )

        payload: Dict[str, Any] = {
            "messages": context_messages,
            "message": prompt or "请发言",
            "task_id": task_id,
        }

        # ── A1: 注入长期记忆（房间级 auto_memory，默认开） ──
        auto_memory = bool((room_snapshot.get("settings") or {}).get("auto_memory", True))
        if auto_memory:
            try:
                from api.websocket.handlers import build_memory_context  # type: ignore
            except Exception:  # pragma: no cover — defensive
                build_memory_context = None  # type: ignore
            if build_memory_context is not None:
                query = _build_memory_query(room_snapshot, prompt)
                if query:
                    try:
                        memory_context, _ = await build_memory_context(query)
                    except Exception as exc:  # pragma: no cover — defensive
                        logger.warning("chatroom memory recall failed: %s", exc)
                        memory_context = ""
                    if memory_context:
                        payload["memory_context"] = memory_context

        # ── A2: 强制群聊文本输出（防御性，当前 Agent 仅在构造时读 output_format，
        # 留 key 待 capability 支持 payload override 时生效；
        # 真正起作用的是下面的 system override 块） ──
        payload["output_format"] = "text"

        _attach_workspace(payload, room_snapshot.get("workspace_id"))
        _attach_chatroom_attachment_context(payload, room_snapshot)

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

        # Spec 2 §9.4 / Task 12 — 自动 mark associated todo as completed
        try:
            related_todos = store.find_todos_by_dispatch(room_id, task_id)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("find_todos_by_dispatch failed: %s", exc)
            related_todos = []
        for todo in related_todos:
            if (todo.get("status") or "") == "completed":
                continue
            updated = store.update_todo(room_id, todo["id"], status="completed")
            if updated:
                await _broadcast(
                    room_id,
                    "chatroom_todo_completed",
                    {
                        "room_id": room_id,
                        "todo_id": todo["id"],
                        "todo": updated,
                        "by": agent_name,
                        "source": "auto",
                    },
                )

        # ── A1: 触发记忆反思（不阻塞接力派发） ──
        if auto_memory and final_text:
            try:
                from api.websocket.handlers import schedule_memory_reflection  # type: ignore
            except Exception:  # pragma: no cover — defensive
                schedule_memory_reflection = None  # type: ignore
            if schedule_memory_reflection is not None:
                try:
                    schedule_memory_reflection(
                        user_message=_build_memory_query(room_after, prompt),
                        assistant_text=final_text,
                        source=f"chatroom:{agent_name}",
                        session_id=f"chatroom:{room_id}",
                    )
                except Exception as exc:  # pragma: no cover — defensive
                    logger.warning("chatroom memory reflection failed: %s", exc)

        # ── 接力派发 ──────────────────────────────────────
        # mention 接力：发言里 @ 了某成员就给该成员派 speaking task。
        # （旧版的 host_directive JSON 文本协议已删除，spec §5.4，Task 8）
        if mentions:
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
        reset_current_parent_message_id(parent_token)
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)


__all__ = [
    "dispatch_speaking_task",
    "maybe_schedule_summary",
]
