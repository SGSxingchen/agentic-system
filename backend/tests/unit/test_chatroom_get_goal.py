"""Unit tests for the chatroom_get_goal tool."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _patch_broadcast(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    # 让工具内部的 broadcast 为 no-op（即使我们这里不广播）
    try:
        monkeypatch.setattr(
            "api.websocket.handlers.broadcast_chatroom_event", _noop, raising=False
        )
    except Exception:
        pass
    yield


@pytest.fixture
def store(tmp_path):
    from core.chatroom import ChatroomStore

    return ChatroomStore(root=tmp_path / "rooms")


@pytest.fixture
def context_room(store):
    """Create room + bind ContextVars; yield (room_id, speaker_name)."""

    from core.task import (
        reset_current_room_id,
        reset_current_speaker_name,
        set_current_room_id,
        set_current_speaker_name,
    )

    room = store.create_room(
        title="t",
        topic="测试主题",
        goal="主目标",
        members=["planner", "coder"],
        dynamic_members=[
            {"name": "writer", "role_prompt": "x", "base_agent": "generic"}
        ],
    )
    room_token = set_current_room_id(room["id"])
    speaker_token = set_current_speaker_name("planner")
    try:
        yield room["id"], "planner"
    finally:
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)


@pytest.mark.asyncio
async def test_returns_topic_goal_summary_members_and_role(store, context_room, monkeypatch):
    from capabilities.tools.chatroom_get_goal import ChatroomGetGoalCapability

    # 让工具内部的 ChatroomStore 指向 fixture 的 store
    monkeypatch.setattr(
        "capabilities.tools.chatroom_get_goal.ChatroomStore",
        lambda *args, **kwargs: store,
    )

    room_id, speaker = context_room
    # 改下 summary 和 add a goal_history entry
    store.update_room(
        room_id, summary="历史决议要点 1, 2", goal_history=[{"goal": "旧目标"}]
    )

    result = await ChatroomGetGoalCapability().execute()

    assert isinstance(result, dict)
    assert result["topic"] == "测试主题"
    assert result["goal"] == "主目标"
    assert result["summary"] == "历史决议要点 1, 2"
    assert result["your_role"] == speaker
    assert "planner" in result["members"]
    assert "coder" in result["members"]
    assert "writer" in result["members"]


@pytest.mark.asyncio
async def test_includes_goal_revisions_count(store, context_room, monkeypatch):
    from capabilities.tools.chatroom_get_goal import ChatroomGetGoalCapability

    monkeypatch.setattr(
        "capabilities.tools.chatroom_get_goal.ChatroomStore",
        lambda *args, **kwargs: store,
    )
    room_id, _ = context_room
    store.update_room(
        room_id,
        goal_history=[
            {"goal": "G0", "set_by": "x"},
            {"goal": "G1", "set_by": "y"},
            {"goal": "G2", "set_by": "z"},
        ],
    )

    result = await ChatroomGetGoalCapability().execute()
    assert result["goal_revisions"] == 3


@pytest.mark.xfail(
    strict=True,
    reason="goal_subgoals data model added in Task 7; remove xfail once landed",
)
@pytest.mark.asyncio
async def test_includes_goal_subgoals_when_set(store, context_room, monkeypatch):
    """Task 7 / A9 增量更新引入 goal_subgoals；本测试确保 get_goal 能读出来。

    Task 6 时 Chatroom 数据模型还没 goal_subgoals 字段（Task 7 会加），所以
    暂时 xfail；Task 7 落地后会自动转 xpass，到时移除 xfail 标记并保留这条
    断言（保护 get_goal 输出契约）。
    """

    from capabilities.tools.chatroom_get_goal import ChatroomGetGoalCapability

    monkeypatch.setattr(
        "capabilities.tools.chatroom_get_goal.ChatroomStore",
        lambda *args, **kwargs: store,
    )
    room_id, _ = context_room
    # 直接更新 raw room JSON (Task 7 才会加官方 helper)
    raw_room = store.get_room(room_id)
    raw_room["goal_subgoals"] = [
        {
            "id": "s1",
            "content": "完成评审",
            "status": "pending",
            "created_at": "2026-05-28T00:00:00Z",
            "done_at": None,
        },
        {
            "id": "s2",
            "content": "完成代码",
            "status": "done",
            "created_at": "2026-05-28T00:00:00Z",
            "done_at": "2026-05-28T01:00:00Z",
        },
    ]
    # 用低层 _write_room 落盘
    store._write_room(raw_room)

    result = await ChatroomGetGoalCapability().execute()
    subs = result.get("goal_subgoals") or []
    assert len(subs) == 2
    assert {s["id"] for s in subs} == {"s1", "s2"}
    for sub in subs:
        assert "content" in sub
        assert "status" in sub


@pytest.mark.asyncio
async def test_outside_room_returns_permission_denied_error():
    from capabilities.tools.chatroom_get_goal import ChatroomGetGoalCapability

    # No ContextVars set
    result = await ChatroomGetGoalCapability().execute()
    assert isinstance(result, dict)
    assert "error" in result
    assert "chatroom" in result["error"].lower()


@pytest.mark.asyncio
async def test_unknown_room_returns_error(monkeypatch, tmp_path):
    from core.chatroom import ChatroomStore
    from core.task import (
        reset_current_room_id,
        reset_current_speaker_name,
        set_current_room_id,
        set_current_speaker_name,
    )
    from capabilities.tools.chatroom_get_goal import ChatroomGetGoalCapability

    empty_store = ChatroomStore(root=tmp_path / "empty")
    monkeypatch.setattr(
        "capabilities.tools.chatroom_get_goal.ChatroomStore",
        lambda *args, **kwargs: empty_store,
    )
    room_token = set_current_room_id("does-not-exist")
    speaker_token = set_current_speaker_name("planner")
    try:
        result = await ChatroomGetGoalCapability().execute()
    finally:
        reset_current_speaker_name(speaker_token)
        reset_current_room_id(room_token)
    assert isinstance(result, dict)
    assert "error" in result
    assert "not found" in result["error"].lower()
