"""Unit tests for the chatroom_update_goal tool (subgoal CRUD + revise)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _patch_broadcast(monkeypatch):
    captured = []

    async def _capture(room_id, event_type, data):
        captured.append({"room_id": room_id, "event_type": event_type, "data": data})

    monkeypatch.setattr(
        "capabilities.tools.chatroom_update_goal._broadcast", _capture, raising=False
    )
    yield captured


@pytest.fixture
def store(tmp_path):
    from core.chatroom import ChatroomStore

    return ChatroomStore(root=tmp_path / "rooms")


@pytest.fixture
def context_room(store):
    from core.task import (
        reset_current_room_id,
        reset_current_speaker_name,
        set_current_room_id,
        set_current_speaker_name,
    )

    room = store.create_room(
        title="t",
        topic="测试",
        goal="主目标 X",
        members=["planner"],
    )
    room_token = set_current_room_id(room["id"])
    speaker_token = set_current_speaker_name("planner")
    try:
        yield room["id"]
    finally:
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)


@pytest.fixture(autouse=True)
def patch_store(monkeypatch, store):
    """Make ChatroomUpdateGoal use the test fixture store."""

    monkeypatch.setattr(
        "capabilities.tools.chatroom_update_goal.ChatroomStore",
        lambda *a, **kw: store,
    )
    yield


@pytest.mark.asyncio
async def test_add_subgoal_appends_to_goal_subgoals(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    result = await ChatroomUpdateGoalCapability().execute(
        operation="add_subgoal", content="完成评审"
    )
    assert result.get("ok") is True
    sub_id = result["subgoal"]["id"]

    fetched = store.get_room(context_room)
    subs = fetched.get("goal_subgoals") or []
    assert len(subs) == 1
    assert subs[0]["id"] == sub_id
    assert subs[0]["status"] == "pending"
    assert subs[0]["content"] == "完成评审"
    assert any(
        e["event_type"] == "chatroom_goal_subgoal_added" for e in _patch_broadcast
    )


@pytest.mark.asyncio
async def test_mark_done_updates_status_and_done_at(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    cap = ChatroomUpdateGoalCapability()
    add_result = await cap.execute(operation="add_subgoal", content="X")
    sub_id = add_result["subgoal"]["id"]

    _patch_broadcast.clear()
    done = await cap.execute(operation="mark_done", subgoal_id=sub_id)
    assert done.get("ok") is True

    fetched = store.get_room(context_room)
    sub = next(s for s in fetched["goal_subgoals"] if s["id"] == sub_id)
    assert sub["status"] == "done"
    assert sub["done_at"]
    assert any(
        e["event_type"] == "chatroom_goal_subgoal_done" for e in _patch_broadcast
    )


@pytest.mark.asyncio
async def test_remove_subgoal_drops_entry(store, context_room):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    cap = ChatroomUpdateGoalCapability()
    a = await cap.execute(operation="add_subgoal", content="A")
    b = await cap.execute(operation="add_subgoal", content="B")
    assert len((store.get_room(context_room) or {}).get("goal_subgoals") or []) == 2

    await cap.execute(operation="remove_subgoal", subgoal_id=a["subgoal"]["id"])

    subs = (store.get_room(context_room) or {}).get("goal_subgoals") or []
    assert len(subs) == 1
    assert subs[0]["id"] == b["subgoal"]["id"]


@pytest.mark.asyncio
async def test_revise_replaces_main_goal_and_archives_old(store, context_room):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    result = await ChatroomUpdateGoalCapability().execute(
        operation="revise", content="brand new goal"
    )
    assert result.get("ok") is True

    fetched = store.get_room(context_room)
    assert fetched["goal"] == "brand new goal"
    history = fetched.get("goal_history") or []
    assert any((entry.get("goal") or "") == "主目标 X" for entry in history)


@pytest.mark.asyncio
async def test_missing_subgoal_id_returns_error(store, context_room):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    result = await ChatroomUpdateGoalCapability().execute(operation="mark_done")
    assert "error" in result


@pytest.mark.asyncio
async def test_unknown_subgoal_id_returns_error(store, context_room):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    result = await ChatroomUpdateGoalCapability().execute(
        operation="mark_done", subgoal_id="ghost-id"
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_outside_room_returns_error():
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    # No ContextVars set
    result = await ChatroomUpdateGoalCapability().execute(
        operation="add_subgoal", content="x"
    )
    assert "error" in result
    assert "chatroom" in result["error"].lower()


@pytest.mark.asyncio
async def test_add_subgoal_without_content_returns_error(store, context_room):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    result = await ChatroomUpdateGoalCapability().execute(operation="add_subgoal")
    assert "error" in result


@pytest.mark.asyncio
async def test_revise_without_content_returns_error(store, context_room):
    from capabilities.tools.chatroom_update_goal import ChatroomUpdateGoalCapability

    result = await ChatroomUpdateGoalCapability().execute(operation="revise")
    assert "error" in result
