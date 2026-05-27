"""Unit tests for the chatroom_dispatch tool — Spec 2 §5.3."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _patch_broadcast(monkeypatch):
    captured = []

    async def _capture(room_id, event_type, data):
        captured.append({"room_id": room_id, "event_type": event_type, "data": data})

    monkeypatch.setattr(
        "capabilities.tools.chatroom_dispatch._broadcast", _capture, raising=False
    )
    yield captured


@pytest.fixture
def store(tmp_path):
    from core.chatroom import ChatroomStore

    return ChatroomStore(root=tmp_path / "rooms")


@pytest.fixture(autouse=True)
def patch_store(monkeypatch, store):
    monkeypatch.setattr(
        "capabilities.tools.chatroom_dispatch.ChatroomStore",
        lambda *a, **kw: store,
    )


@pytest.fixture
def patched_dispatch(monkeypatch):
    """Stub dispatch_speaking_task to inspect calls without running real tasks."""

    calls = []

    def _fake_dispatch(room_id, agent_name, **kwargs):
        ticket = {
            "task_id": f"task-{len(calls) + 1}",
            "agent_name": agent_name,
            "message_id": f"msg-{len(calls) + 1}",
        }
        calls.append({"room_id": room_id, "agent_name": agent_name, **kwargs})
        return ticket

    monkeypatch.setattr(
        "capabilities.tools.chatroom_dispatch.dispatch_speaking_task",
        _fake_dispatch,
    )
    return calls


@pytest.fixture
def context_room(store):
    from core.task import (
        reset_current_parent_message_id,
        reset_current_room_id,
        reset_current_speaker_name,
        set_current_parent_message_id,
        set_current_room_id,
        set_current_speaker_name,
    )

    room = store.create_room(
        title="t",
        members=["planner", "coder", "reviewer"],
    )
    room_token = set_current_room_id(room["id"])
    speaker_token = set_current_speaker_name("planner")
    parent_token = set_current_parent_message_id("placeholder-msg-id")
    try:
        yield room["id"]
    finally:
        reset_current_parent_message_id(parent_token)
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)


@pytest.mark.asyncio
async def test_dispatch_single_agent_creates_speaking_task(
    store, context_room, patched_dispatch, _patch_broadcast
):
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    result = await ChatroomDispatchCapability().execute(
        actions=[{"agent": "reviewer"}]
    )

    assert isinstance(result, dict)
    dispatched = result.get("dispatched") or []
    assert len(dispatched) == 1
    assert dispatched[0]["agent"] == "reviewer"
    assert dispatched[0]["status"] == "dispatched"
    assert "task_id" in dispatched[0]
    assert result.get("failed") == []
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["agent_name"] == "reviewer"


@pytest.mark.asyncio
async def test_dispatch_multiple_agents_returns_all_dispatched(
    store, context_room, patched_dispatch
):
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    result = await ChatroomDispatchCapability().execute(
        actions=[{"agent": "reviewer"}, {"agent": "coder"}]
    )

    assert {d["agent"] for d in result["dispatched"]} == {"reviewer", "coder"}
    assert len(patched_dispatch) == 2


@pytest.mark.asyncio
async def test_dispatch_unknown_agent_lands_in_failed_with_reason(
    store, context_room, patched_dispatch
):
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    result = await ChatroomDispatchCapability().execute(
        actions=[{"agent": "nonexistent"}]
    )

    failed = result.get("failed") or []
    assert len(failed) == 1
    assert failed[0]["agent"] == "nonexistent"
    assert failed[0]["reason"] == "member_not_in_room"
    # 不存在的 agent 不应实际派发
    assert patched_dispatch == []


@pytest.mark.asyncio
async def test_dispatch_passes_prompt_through(store, context_room, patched_dispatch):
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    await ChatroomDispatchCapability().execute(
        actions=[{"agent": "reviewer", "prompt": "评一下"}]
    )

    assert len(patched_dispatch) == 1
    assert patched_dispatch[0].get("prompt") == "评一下"


@pytest.mark.asyncio
async def test_dispatch_outside_room_returns_permission_denied():
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    # 不设 ContextVars
    result = await ChatroomDispatchCapability().execute(
        actions=[{"agent": "reviewer"}]
    )
    assert "error" in result
    assert "chatroom" in result["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_empty_actions_returns_error(store, context_room):
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    result = await ChatroomDispatchCapability().execute(actions=[])
    assert "error" in result
    assert "non-empty" in result["error"].lower() or "empty" in result["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_includes_parent_message_id_when_available(
    store, context_room, patched_dispatch
):
    """ContextVar parent_message_id 应被 dispatch 工具读到并透传给 dispatch_speaking_task。"""

    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    await ChatroomDispatchCapability().execute(actions=[{"agent": "reviewer"}])

    assert len(patched_dispatch) == 1
    assert patched_dispatch[0].get("parent_message_id") == "placeholder-msg-id"


@pytest.mark.asyncio
async def test_dispatch_broadcasts_chatroom_dispatch_called(
    store, context_room, patched_dispatch, _patch_broadcast
):
    from capabilities.tools.chatroom_dispatch import ChatroomDispatchCapability

    await ChatroomDispatchCapability().execute(
        actions=[{"agent": "reviewer"}, {"agent": "coder"}]
    )

    matching = [
        e for e in _patch_broadcast if e["event_type"] == "chatroom_dispatch_called"
    ]
    assert len(matching) == 1
    data = matching[0]["data"]
    assert data["room_id"] == context_room
    assert data["dispatcher"] == "planner"
    assert set(data["dispatched_task_ids"]) == {"task-1", "task-2"}
