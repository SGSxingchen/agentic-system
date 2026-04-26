"""WebSocket connection management and server-side event bridging."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..dependencies import get_capability_registry, get_memory_formation

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
    cap = cap_registry.get("assistant") if cap_registry else None
    if cap is None:
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

    stream_fn = getattr(cap, "execute_stream", None)
    if stream_fn is None:
        # 兜底：不支持流式时回退到一次性调用
        try:
            result = await cap_registry.execute("assistant", message=user_message)
            response_text = result.get("response", str(result))
        except Exception as exc:
            response_text = f"Processing failed: {exc}"
        await manager.send_to(
            websocket,
            _ws_message(
                "assistant_response",
                {"response": response_text, "original_message": user_message},
            ),
        )
        return

    response_text = ""
    try:
        async for event in stream_fn(message=user_message):
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
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "tool": event.get("tool"),
                            "args": event.get("args"),
                            "concurrent": bool(event.get("concurrent")),
                        },
                        event_type="agent_tool_call",
                    ),
                )

            elif etype == "tool_result":
                await manager.send_to(
                    websocket,
                    _ws_message(
                        "event",
                        {
                            "tool": event.get("tool"),
                            "result": event.get("result"),
                            "truncated": bool(event.get("truncated")),
                        },
                        event_type="agent_tool_result",
                    ),
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
                        },
                    ),
                )
                response_text = final_text

        formation = get_memory_formation()
        if formation:
            try:
                await formation.create_episodic(
                    event_description=(
                        f"User: {user_message}\nAssistant: {response_text[:200]}"
                    ),
                    source="assistant_agent",
                    importance=0.4,
                )
            except Exception:
                pass

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
