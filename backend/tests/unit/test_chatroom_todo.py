"""Unit tests for the chatroom_todo tool — Spec 2 §9."""
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
        "capabilities.tools.chatroom_todo._broadcast", _capture, raising=False
    )
    yield captured


@pytest.fixture
def store(tmp_path):
    from core.chatroom import ChatroomStore

    return ChatroomStore(root=tmp_path / "rooms")


@pytest.fixture(autouse=True)
def patch_store(monkeypatch, store):
    monkeypatch.setattr(
        "capabilities.tools.chatroom_todo.ChatroomStore",
        lambda *a, **kw: store,
    )


@pytest.fixture
def context_room(store):
    from core.task import (
        reset_current_room_id,
        reset_current_speaker_name,
        set_current_room_id,
        set_current_speaker_name,
    )

    room = store.create_room(
        title="t", members=["planner", "reviewer", "coder"]
    )
    room_token = set_current_room_id(room["id"])
    speaker_token = set_current_speaker_name("planner")
    try:
        yield room["id"]
    finally:
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)


@pytest.mark.asyncio
async def test_create_appends_todos_to_room(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    result = await ChatroomTodoCapability().execute(
        action="create",
        todos=[{"content": "X"}, {"content": "Y", "assignee": "reviewer"}],
    )
    assert result.get("ok") is True
    fetched = store.get_room(context_room)
    todos = fetched.get("todos") or []
    assert len(todos) == 2
    contents = {t["content"] for t in todos}
    assert contents == {"X", "Y"}
    matching = [e for e in _patch_broadcast if e["event_type"] == "chatroom_todo_added"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_create_assigns_pending_status_and_timestamps(store, context_room):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    result = await ChatroomTodoCapability().execute(
        action="create", todos=[{"content": "Z"}]
    )
    todo = result["todos"][0]
    assert todo["status"] == "pending"
    assert todo["created_at"]
    assert todo["updated_at"]
    assert len(todo["id"]) >= 8


@pytest.mark.asyncio
async def test_complete_sets_status_completed_and_timestamp(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    cap = ChatroomTodoCapability()
    create = await cap.execute(action="create", todos=[{"content": "A"}])
    todo_id = create["todos"][0]["id"]
    initial_updated_at = create["todos"][0]["updated_at"]

    _patch_broadcast.clear()
    done = await cap.execute(action="complete", todo_id=todo_id)
    assert done.get("ok") is True
    fetched = store.get_room(context_room)
    todo = next(t for t in fetched["todos"] if t["id"] == todo_id)
    assert todo["status"] == "completed"
    assert todo["updated_at"] >= initial_updated_at
    assert any(e["event_type"] == "chatroom_todo_completed" for e in _patch_broadcast)


@pytest.mark.asyncio
async def test_block_sets_status_and_optional_notes(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    cap = ChatroomTodoCapability()
    todo_id = (await cap.execute(action="create", todos=[{"content": "B"}]))["todos"][0]["id"]

    _patch_broadcast.clear()
    result = await cap.execute(action="block", todo_id=todo_id, notes="waiting on X")
    assert result.get("ok") is True
    fetched = store.get_room(context_room)
    todo = next(t for t in fetched["todos"] if t["id"] == todo_id)
    assert todo["status"] == "blocked"
    assert todo["notes"] == "waiting on X"
    assert any(e["event_type"] == "chatroom_todo_updated" for e in _patch_broadcast)


@pytest.mark.asyncio
async def test_update_modifies_content_or_assignee(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    cap = ChatroomTodoCapability()
    todo_id = (await cap.execute(action="create", todos=[{"content": "C"}]))["todos"][0]["id"]

    _patch_broadcast.clear()
    result = await cap.execute(action="update", todo_id=todo_id, content="Z")
    assert result.get("ok") is True
    fetched = store.get_room(context_room)
    todo = next(t for t in fetched["todos"] if t["id"] == todo_id)
    assert todo["content"] == "Z"
    assert any(e["event_type"] == "chatroom_todo_updated" for e in _patch_broadcast)


@pytest.mark.asyncio
async def test_delete_removes_todo(store, context_room, _patch_broadcast):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    cap = ChatroomTodoCapability()
    todo_id = (await cap.execute(action="create", todos=[{"content": "D"}]))["todos"][0]["id"]

    _patch_broadcast.clear()
    result = await cap.execute(action="delete", todo_id=todo_id)
    assert result.get("ok") is True
    fetched = store.get_room(context_room)
    assert all(t["id"] != todo_id for t in (fetched.get("todos") or []))
    assert any(e["event_type"] == "chatroom_todo_deleted" for e in _patch_broadcast)


@pytest.mark.asyncio
async def test_list_returns_all_todos_grouped_by_status(store, context_room):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    cap = ChatroomTodoCapability()
    await cap.execute(
        action="create",
        todos=[
            {"content": "P1"},
            {"content": "P2"},
        ],
    )
    todos_after_create = (await cap.execute(action="list"))["todos"]
    assert len(todos_after_create) == 2
    contents = [t["content"] for t in todos_after_create]
    assert contents == ["P1", "P2"]


@pytest.mark.asyncio
async def test_unknown_todo_id_returns_error(store, context_room):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    result = await ChatroomTodoCapability().execute(
        action="complete", todo_id="ghost"
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_outside_room_returns_permission_denied():
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    result = await ChatroomTodoCapability().execute(
        action="create", todos=[{"content": "X"}]
    )
    assert "error" in result
    assert "chatroom" in result["error"].lower()


@pytest.mark.asyncio
async def test_create_without_todos_returns_error(store, context_room):
    from capabilities.tools.chatroom_todo import ChatroomTodoCapability

    result = await ChatroomTodoCapability().execute(action="create")
    assert "error" in result
