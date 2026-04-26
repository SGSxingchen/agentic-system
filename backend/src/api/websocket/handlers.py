"""WebSocket connection management and server-side event bridging."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from core.memory import MemoryProcessor

from ..dependencies import (
    get_capability_registry,
    get_llm_client,
    get_memory_buffer,
    get_memory_formation,
    get_memory_retriever,
)

_BRIDGED_EVENT_TYPES = ("step_started", "step_completed")
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
    """Process a chat message and reply only to the originating socket."""

    user_message = payload.get("text", payload.get("message", "")).strip()
    if not user_message:
        return

    cap_registry = get_capability_registry()
    if not cap_registry or "assistant" not in cap_registry:
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

    try:
        memory_context, memories_used = await build_memory_context(user_message)
        session_id = payload.get("session_id") or payload.get("chat_session_id")
        assistant_payload = {"message": user_message}
        if memory_context:
            assistant_payload["memory_context"] = memory_context

        result = await cap_registry.execute("assistant", **assistant_payload)
        response_text = result.get("response", str(result))

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

        await reflect_chat_exchange(
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
                    "response": f"Processing failed: {str(exc)}",
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
        )
        if not window:
            return

        processor = MemoryProcessor(llm_client)
        candidates = await processor.process_conversation(
            window["turns"],
            source_window=window["source_window"],
        )
        for candidate in candidates:
            await formation.create_structured_memory(candidate)
    except Exception as exc:
        print(f"[WARN] memory reflection failed: {exc}")


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
