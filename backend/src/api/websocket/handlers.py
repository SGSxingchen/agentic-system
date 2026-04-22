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
        result = await cap_registry.execute("assistant", message=user_message)
        response_text = result.get("response", str(result))

        await manager.send_to(
            websocket,
            _ws_message(
                "assistant_response",
                {
                    "response": response_text,
                    "original_message": user_message,
                },
            ),
        )

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
                    "response": f"Processing failed: {str(exc)}",
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
