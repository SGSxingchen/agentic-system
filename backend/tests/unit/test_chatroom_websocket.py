"""Tests for the Phase 2 WebSocket channel mechanism."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.websocket.handlers import (
    ConnectionManager,
    broadcast_chatroom_event,
    chatroom_channel,
    manager as global_manager,
    websocket_endpoint,
)


# ─── ConnectionManager unit tests ──────────────────────────


class _FakeWebSocket:
    """Minimal WebSocket double for unit-level channel tests."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.fail_next: bool = False

    async def send_json(self, message: Dict[str, Any]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("simulated drop")
        self.sent.append(message)


@pytest.mark.asyncio
async def test_subscribe_and_broadcast_to_channel():
    manager = ConnectionManager()
    socket = _FakeWebSocket()
    other = _FakeWebSocket()
    # 不需要 connect — channel API 与 connection list 解耦
    manager.subscribe(socket, "chatroom:R1")
    manager.subscribe(socket, "chatroom:R1")  # idempotent
    manager.subscribe(other, "chatroom:R2")

    assert socket in manager.channel_subscribers("chatroom:R1")
    assert socket not in manager.channel_subscribers("chatroom:R2")

    await manager.broadcast_to_channel("chatroom:R1", {"hello": "R1"})
    assert socket.sent == [{"hello": "R1"}]
    assert other.sent == []


@pytest.mark.asyncio
async def test_unsubscribe_clears_socket():
    manager = ConnectionManager()
    socket = _FakeWebSocket()
    manager.subscribe(socket, "chatroom:R1")
    manager.unsubscribe(socket, "chatroom:R1")

    assert manager.channel_subscribers("chatroom:R1") == []
    await manager.broadcast_to_channel("chatroom:R1", {"hello": "R1"})
    assert socket.sent == []


@pytest.mark.asyncio
async def test_disconnect_purges_all_subscriptions():
    manager = ConnectionManager()
    socket = _FakeWebSocket()
    manager.subscribe(socket, "chatroom:R1")
    manager.subscribe(socket, "chatroom:R2")
    # ConnectionManager.disconnect should clean both channels
    manager.disconnect(socket)

    assert manager.channel_subscribers("chatroom:R1") == []
    assert manager.channel_subscribers("chatroom:R2") == []


@pytest.mark.asyncio
async def test_failing_socket_is_removed_during_broadcast():
    manager = ConnectionManager()
    bad = _FakeWebSocket()
    bad.fail_next = True
    good = _FakeWebSocket()
    manager.subscribe(bad, "chatroom:R1")
    manager.subscribe(good, "chatroom:R1")

    await manager.broadcast_to_channel("chatroom:R1", {"x": 1})

    assert good.sent == [{"x": 1}]
    assert bad not in manager.channel_subscribers("chatroom:R1")


def test_chatroom_channel_helper():
    assert chatroom_channel("abc") == "chatroom:abc"


# ─── End-to-end TestClient WebSocket ───────────────────────


def _build_ws_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_websocket_route("/ws", websocket_endpoint)

    @app.post("/_test/broadcast")
    async def trigger_broadcast(payload: dict):
        await broadcast_chatroom_event(
            payload["room_id"],
            payload["event_type"],
            payload.get("data", {}),
        )
        return {"ok": True}

    return app


def test_websocket_subscribe_unsubscribe_round_trip():
    """Through TestClient: subscribe → broadcast hits us → unsubscribe → silence."""

    # 重置全局 manager 的频道表，避免上一条测试残留
    global_manager._channels.clear()

    app = _build_ws_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"event_type": "subscribe", "channel": "chatroom:room-A"})
        ack = ws.receive_json()
        assert ack["event_type"] == "subscribed"
        assert ack["data"]["channel"] == "chatroom:room-A"
        assert ack["data"]["subscribed"] is True

        # 通过 HTTP 触发后端广播；ASGI 调度链确保它落到 ws 的同一个事件循环里
        resp = client.post(
            "/_test/broadcast",
            json={
                "room_id": "room-A",
                "event_type": "chatroom_message_added",
                "data": {"hello": "world"},
            },
        )
        assert resp.status_code == 200

        msg = ws.receive_json()
        assert msg["event_type"] == "chatroom_message_added"
        assert msg["data"]["hello"] == "world"
        assert msg["data"]["room_id"] == "room-A"

        ws.send_json({"event_type": "unsubscribe", "channel": "chatroom:room-A"})
        ack2 = ws.receive_json()
        assert ack2["event_type"] == "unsubscribed"
        assert ack2["data"]["subscribed"] is False

        # 再触发一次广播；这次本 socket 不再订阅，应不会被推送到
        resp2 = client.post(
            "/_test/broadcast",
            json={
                "room_id": "room-A",
                "event_type": "chatroom_message_added",
                "data": {"second": True},
            },
        )
        assert resp2.status_code == 200

        # ping 一发，验证下条收到的是 pong（说明上一条没被推送过来）
        ws.send_json({"event_type": "ping"})
        pong = ws.receive_json()
        assert pong["event_type"] == "pong"


def test_websocket_unsupported_event_type_returns_notice():
    app = _build_ws_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"event_type": "totally-unknown"})
        msg = ws.receive_json()
        assert msg["event_type"] == "unsupported_event"
        assert msg["data"]["requested_event_type"] == "totally-unknown"


# ─── Task 15: chatroom_dispatch_called event ─────────────────


@pytest.mark.asyncio
async def test_chatroom_dispatch_called_event_broadcasted(monkeypatch, tmp_path):
    """Spec 2 §12 / Task 15 — chatroom_dispatch.execute 成功时广播一次
    chatroom_dispatch_called，payload 包含 room_id / dispatcher /
    dispatched_task_ids / actions。"""

    from core.chatroom import ChatroomStore
    from core.task import (
        reset_current_parent_message_id,
        reset_current_room_id,
        reset_current_speaker_name,
        set_current_parent_message_id,
        set_current_room_id,
        set_current_speaker_name,
    )
    from capabilities.tools import chatroom_dispatch as dispatch_mod

    # 隔离 store
    store = ChatroomStore(root=tmp_path / "rooms")
    monkeypatch.setattr(dispatch_mod, "ChatroomStore", lambda *a, **k: store)

    # 让真实 dispatch_speaking_task stub 出 task_id
    def _fake(room_id, agent_name, **kwargs):
        return {"task_id": f"t-{agent_name}", "agent_name": agent_name, "message_id": "m"}

    monkeypatch.setattr(dispatch_mod, "dispatch_speaking_task", _fake)

    # 捕获 broadcast
    captured = []

    async def _capture(room_id, event_type, data):
        captured.append({"room_id": room_id, "event_type": event_type, "data": data})

    monkeypatch.setattr(dispatch_mod, "_broadcast", _capture)

    room = store.create_room(title="t", members=["planner", "reviewer"])
    rt = set_current_room_id(room["id"])
    st = set_current_speaker_name("planner")
    pt = set_current_parent_message_id("placeholder-msg")
    try:
        result = await dispatch_mod.ChatroomDispatchCapability().execute(
            actions=[{"agent": "reviewer", "prompt": "x"}]
        )
    finally:
        reset_current_parent_message_id(pt)
        reset_current_speaker_name(st)
        reset_current_room_id(rt)

    assert result.get("dispatched")
    matching = [
        e for e in captured if e["event_type"] == "chatroom_dispatch_called"
    ]
    assert len(matching) == 1
    data = matching[0]["data"]
    assert data["room_id"] == room["id"]
    assert data["dispatcher"] == "planner"
    assert data["dispatched_task_ids"] == ["t-reviewer"]
    assert data["actions"] == [{"agent": "reviewer", "task_id": "t-reviewer"}]
