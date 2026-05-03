"""WebSocket connection management and server-side event bridging."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from core.memory import MemoryProcessor, should_reflect_early

from ..dependencies import (
    get_capability_registry,
    get_llm_client,
    get_memory_buffer,
    get_memory_formation,
    get_memory_retriever,
)

_BRIDGED_EVENT_TYPES = (
    "step_started",
    "step_completed",
    "step_failed",
    "step_skipped",
    "agent_progress",
    "tool_call_started",
    "tool_call_finished",
)
_REGISTERED_BUS_IDS: set[int] = set()


def _timestamp() -> str:
    return datetime.utcnow().isoformat()


def _ws_message(
    message_type: str,
    data: dict[str, Any] | None = None,
    *,
    event_type: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": message_type,
        "data": data or {},
        "timestamp": _timestamp(),
    }
    if event_type:
        payload["event_type"] = event_type
    return payload


class ConnectionManager:
    """Track active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    @property
    def active_count(self) -> int:
        return len(self._connections)

    @property
    def connections(self) -> list[WebSocket]:
        """Expose a copy for backward-compatible inspection in callers/tests."""
        return list(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        print(f"[WS] connected ({self.active_count} active)")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        print(f"[WS] disconnected ({self.active_count} active)")

    async def broadcast(self, message: dict[str, Any]) -> None:
        disconnected: list[WebSocket] = []
        for websocket in self._connections:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket)

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


manager = ConnectionManager()


async def broadcast_monitor_event(
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Broadcast an observability event to monitor clients.

    Chat responses still travel through SSE/WebSocket direct replies, but
    progress/tool events are also mirrored here so the Monitor panel can show
    what an Agent is doing right now.
    """

    await manager.broadcast(_ws_message("event", data or {}, event_type=event_type))


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle client WebSocket connections."""

    await manager.connect(websocket)

    try:
        while True:
            payload = await websocket.receive_json()
            event_type = payload.get("event_type", "user_message")

            if event_type == "user_message":
                await _handle_user_message(websocket, payload)
            elif event_type == "ping":
                await manager.send_to(
                    websocket,
                    _ws_message("event", {"message": "pong"}, event_type="pong"),
                )
            else:
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "message": "unsupported client event",
                            "requested_event_type": event_type,
                        },
                        event_type="unsupported_event",
                    ),
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[WS] error: {exc}")
    finally:
        manager.disconnect(websocket)


async def _handle_user_message(
    websocket: WebSocket,
    payload: dict[str, Any],
) -> None:
    """Process a chat message via the streaming Agent loop and reply only to the originating socket.

    Emits the following event types to the client (in order):
      - agent_thinking      — incremental text deltas from the LLM
      - agent_tool_call     — Agent decided to invoke a tool (concurrent flag attached)
      - agent_tool_result   — tool finished; result dict + truncated flag
      - agent_done          — stream complete, includes usage metrics
      - assistant_response  — final text content (kept for backward compatibility with the
                              existing ChatPanel implementation)

    Errors fall back to a single ``assistant_response`` event so the UI keeps working.
    """

    user_message = payload.get("text", payload.get("message", "")).strip()
    if not user_message:
        return

    cap_registry = get_capability_registry()
    cap = cap_registry.get("assistant") if cap_registry and hasattr(cap_registry, "get") else None
    if cap_registry is None or (cap is None and "assistant" not in cap_registry):
        await manager.send_to(
            websocket,
            _ws_message(
                "assistant_response",
                {
                    "response": "Assistant is not initialized.",
                    "original_message": user_message,
                },
            ),
        )
        return

    memory_context, memories_used = await build_memory_context(user_message)
    session_id = payload.get("session_id") or payload.get("chat_session_id")
    assistant_payload = {"message": user_message}
    if memory_context:
        assistant_payload["memory_context"] = memory_context

    stream_fn = getattr(cap, "execute_stream", None)
    if stream_fn is None:
        # 兜底：不支持流式时回退到一次性调用
        try:
            result = await cap_registry.execute("assistant", **assistant_payload)
            response_text = result.get("response", str(result))
        except Exception as exc:
            response_text = f"Processing failed: {exc}"

        await manager.send_to(
            websocket,
            _ws_message(
                "assistant_response",
                {
                    "response": response_text,
                    "original_message": user_message,
                    "memories_used": memories_used,
                },
            ),
        )
        schedule_memory_reflection(
            user_message=user_message,
            assistant_text=response_text,
            source="websocket_chat",
            session_id=str(session_id) if session_id else None,
        )
        return

    response_text = ""
    tool_started_at: dict[str, datetime] = {}
    try:
        await manager.send_to(
            websocket,
            _ws_message(
                "event",
                {
                    "agent": "assistant",
                    "activity": "planning",
                    "status": "running",
                    "message": "Preparing context and contacting LLM",
                },
                event_type="agent_progress",
            ),
        )
        async for event in stream_fn(**assistant_payload):
            etype = event.get("type")

            if etype == "thinking":
                content = event.get("content") or ""
                response_text += content
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {"content": content},
                        event_type="agent_thinking",
                    ),
                )

            elif etype == "tool_call":
                tool_name = str(event.get("tool") or "")
                call_id = str(event.get("tool_call_id") or f"{tool_name}:{len(tool_started_at) + 1}")
                tool_started_at[call_id] = datetime.utcnow()
                progress_data = {
                    "agent": "assistant",
                    "activity": "calling_tool",
                    "status": "running",
                    "tool": tool_name,
                    "tool_call_id": call_id,
                }
                await manager.send_to(
                    websocket,
                    _ws_message("event", progress_data, event_type="agent_progress"),
                )
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "tool": tool_name,
                            "tool_call_id": call_id,
                            "args": event.get("args"),
                            "concurrent": bool(event.get("concurrent")),
                            "status": "running",
                        },
                        event_type="agent_tool_call",
                    ),
                )
                await broadcast_monitor_event(
                    "tool_call_started",
                    {
                        **progress_data,
                        "args": event.get("args"),
                        "concurrent": bool(event.get("concurrent")),
                    },
                )

            elif etype == "tool_result":
                tool_name = str(event.get("tool") or "")
                call_id = str(event.get("tool_call_id") or f"{tool_name}:latest")
                started = tool_started_at.pop(call_id, None)
                elapsed_ms = (
                    round((datetime.utcnow() - started).total_seconds() * 1000, 2)
                    if started
                    else None
                )
                result = event.get("result")
                is_error = isinstance(result, dict) and bool(result.get("error"))
                progress_data = {
                    "agent": "assistant",
                    "activity": "waiting",
                    "status": "error" if is_error else "running",
                    "tool": tool_name,
                    "tool_call_id": call_id,
                    "elapsed_ms": elapsed_ms,
                }
                await manager.send_to(
                    websocket,
                    _ws_message("event", progress_data, event_type="agent_progress"),
                )
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "tool": tool_name,
                            "tool_call_id": call_id,
                            "result": result,
                            "status": "error" if is_error else "success",
                            "elapsed_ms": elapsed_ms,
                            "truncated": bool(event.get("truncated")),
                        },
                        event_type="agent_tool_result",
                    ),
                )
                await broadcast_monitor_event(
                    "tool_call_finished",
                    {
                        **progress_data,
                        "status": "error" if is_error else "success",
                        "result": result,
                        "truncated": bool(event.get("truncated")),
                    },
                )

            elif etype == "done":
                content = event.get("content")
                final_text: str
                if isinstance(content, dict):
                    final_text = content.get("response") or content.get("error") or response_text
                else:
                    final_text = str(content) if content is not None else response_text

                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "usage": event.get("usage"),
                            "elapsed_ms": event.get("elapsed_ms"),
                            "final": final_text,
                        },
                        event_type="agent_done",
                    ),
                )
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "agent": "assistant",
                            "activity": "completed",
                            "status": "completed",
                            "elapsed_ms": event.get("elapsed_ms"),
                        },
                        event_type="agent_progress",
                    ),
                )
                # 兼容现有前端：仍然下发 assistant_response 携带最终文本
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "assistant_response",
                        {
                            "response": final_text,
                            "original_message": user_message,
                            "usage": event.get("usage"),
                            "elapsed_ms": event.get("elapsed_ms"),
                            "memories_used": memories_used,
                        },
                    ),
                )
                response_text = final_text

        schedule_memory_reflection(
            user_message=user_message,
            assistant_text=response_text,
            source="websocket_chat",
            session_id=str(session_id) if session_id else None,
        )
    except Exception as exc:
        await manager.send_to(
            websocket,
            _ws_message(
                "assistant_response",
                {
                    "response": f"Processing failed: {exc}",
                    "original_message": user_message,
                },
            ),
        )


async def build_memory_context(
    query: str,
    *,
    max_results: int = 3,
    max_chars: int = 1200,
) -> tuple[str, int]:
    """Build a compact memory block for Assistant system prompt injection."""

    retriever = get_memory_retriever()
    if not retriever or not query.strip():
        return "", 0

    try:
        if hasattr(retriever, "retrieve_with_scores"):
            scored = await retriever.retrieve_with_scores(query, max_results=max_results)
            memories = [item["memory"] for item in scored]
        else:
            memories = await retriever.retrieve(query, max_results=max_results)
    except Exception as exc:
        print(f"[WARN] memory recall failed: {exc}")
        return "", 0

    lines: list[str] = []
    remaining = max_chars
    for memory in memories:
        metadata = memory.metadata or {}
        text = str(
            metadata.get("assistant_context")
            or metadata.get("canonical_summary")
            or memory.content
        ).strip()
        if not text:
            continue
        line = f"- {text}"
        if len(line) > remaining:
            break
        lines.append(line)
        remaining -= len(line)

    if lines:
        print(f"[MEMORY] recalled {len(lines)} memories for query={query[:80]!r}")
    return "\n".join(lines), len(lines)


async def reflect_chat_exchange(
    *,
    user_message: str,
    assistant_text: str,
    source: str,
    session_id: str | None = None,
) -> None:
    """Append a chat exchange and reflect it into structured memories when ready."""

    buffer = get_memory_buffer()
    formation = get_memory_formation()
    llm_client = get_llm_client()
    if not buffer or not formation or not llm_client:
        return

    try:
        window = buffer.append_exchange(
            user_message,
            assistant_text,
            source=source,
            session_id=session_id,
            significant=should_reflect_early(user_message),
        )
        if not window:
            return

        processor = MemoryProcessor(llm_client)
        candidates = await processor.process_conversation(
            window["turns"],
            source_window=window["source_window"],
        )
        saved = 0
        for candidate in candidates:
            memory = await formation.create_structured_memory(candidate)
            if memory:
                saved += 1
        print(
            "[MEMORY] reflected chat window "
            f"source={source} session_id={session_id or '-'} "
            f"trigger={window['source_window'].get('trigger_reason')} "
            f"candidates={len(candidates)} saved={saved}"
        )
    except Exception as exc:
        print(f"[WARN] memory reflection failed: {exc}")


def schedule_memory_reflection(
    *,
    user_message: str,
    assistant_text: str,
    source: str,
    session_id: str | None = None,
) -> asyncio.Task | None:
    """Schedule chat reflection in the background and swallow task errors."""

    try:
        task = asyncio.create_task(
            reflect_chat_exchange(
                user_message=user_message,
                assistant_text=assistant_text,
                source=source,
                session_id=session_id,
            ),
            name=f"memory-reflection:{source}",
        )
    except RuntimeError:
        # No running loop. This should not happen in FastAPI paths, but keeping
        # the function safe makes direct script/test calls easier to reason about.
        print("[WARN] memory reflection was not scheduled: no running event loop")
        return None

    def _log_task_result(done: asyncio.Task) -> None:
        try:
            done.result()
        except Exception as exc:  # pragma: no cover - reflect_chat_exchange catches internally
            print(f"[WARN] background memory reflection failed: {exc}")

    task.add_done_callback(_log_task_result)
    return task


def register_bus_event_bridge(bus: Any) -> None:
    """Broadcast safe pipeline events to every connected monitor client."""

    bus_id = id(bus)
    if bus_id in _REGISTERED_BUS_IDS:
        return

    async def _forward_event(event: Any) -> None:
        data = event.data if isinstance(event.data, dict) else {"payload": event.data}
        safe_data = dict(data)
        safe_data.setdefault("source", event.source)
        await manager.broadcast(
            _ws_message("event", safe_data, event_type=event.event_type)
        )

    for event_type in _BRIDGED_EVENT_TYPES:
        bus.subscribe(event_type, _forward_event)

    _REGISTERED_BUS_IDS.add(bus_id)
