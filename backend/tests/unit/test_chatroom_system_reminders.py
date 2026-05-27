"""Unit tests for build_system_reminders — Spec 2 §8."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_build_system_reminders_returns_empty_when_nothing_changed():
    from core.chatroom_reminders import build_system_reminders

    room = {
        "messages": [],
        "members": ["planner"],
        "dynamic_members": [],
        "goal_history": [],
    }
    result = build_system_reminders(room, target_agent="planner", parent_message_id=None)
    assert result == ""


def test_includes_goal_change_when_goal_modified_after_last_speech():
    from core.chatroom_reminders import build_system_reminders

    room = {
        "goal": "新目标",
        "goal_history": [
            {"goal": "旧目标", "set_by": "user", "set_at": "2026-05-28T01:30:00Z"},
        ],
        "messages": [
            {
                "id": "p1",
                "sender": "agent:planner",
                "content": "x",
                "status": "done",
                "created_at": "2026-05-28T00:00:00Z",
            },
            {
                "id": "u1",
                "sender": "user",
                "content": "y",
                "status": "done",
                "created_at": "2026-05-28T02:00:00Z",
            },
        ],
        "members": ["planner"],
        "dynamic_members": [],
    }
    result = build_system_reminders(
        room, target_agent="planner", parent_message_id=None
    )
    # 必含 "目标在你上次发言后被" + 新 goal
    assert "目标" in result and "上次发言后" in result
    assert "新目标" in result


def test_includes_new_member_added_after_last_speech():
    from core.chatroom_reminders import build_system_reminders

    room = {
        "messages": [
            {
                "id": "p1",
                "sender": "agent:planner",
                "content": "x",
                "status": "done",
                "created_at": "2026-05-28T00:00:00Z",
            },
        ],
        "members": ["planner"],
        "dynamic_members": [
            {"name": "writer", "joined_at": "2026-05-28T01:30:00Z", "role_prompt": ""}
        ],
        "goal_history": [],
    }
    result = build_system_reminders(
        room, target_agent="planner", parent_message_id=None
    )
    assert "新成员" in result or "writer" in result


def test_includes_at_mention_marker_when_parent_message_mentions_speaker():
    from core.chatroom_reminders import build_system_reminders

    room = {
        "messages": [
            {
                "id": "u1",
                "sender": "user",
                "content": "@reviewer 评审",
                "status": "done",
                "mentions": ["reviewer"],
                "created_at": "2026-05-28T01:00:00Z",
            },
        ],
        "members": ["reviewer", "planner"],
        "dynamic_members": [],
        "goal_history": [],
    }
    result = build_system_reminders(
        room, target_agent="reviewer", parent_message_id="u1"
    )
    assert "@" in result and ("被" in result or "刚被" in result)


def test_truncates_to_first_three_when_too_many_signals():
    from core.chatroom_reminders import build_system_reminders

    # 构造大量信号：goal 变化 + 多个新成员 + mention
    room = {
        "goal": "newest",
        "goal_history": [
            {"goal": "v1", "set_by": "user", "set_at": "2026-05-28T01:00:00Z"},
        ],
        "messages": [
            {
                "id": "p1",
                "sender": "agent:planner",
                "content": "x",
                "status": "done",
                "created_at": "2026-05-28T00:00:00Z",
            },
            {
                "id": "u1",
                "sender": "user",
                "content": "@planner ?",
                "status": "done",
                "mentions": ["planner"],
                "created_at": "2026-05-28T02:00:00Z",
            },
        ],
        "members": ["planner"],
        "dynamic_members": [
            {"name": f"new{i}", "joined_at": "2026-05-28T01:30:00Z", "role_prompt": ""}
            for i in range(5)
        ],
        "goal_subgoals": [],
    }
    result = build_system_reminders(
        room, target_agent="planner", parent_message_id="u1"
    )
    # 最多 3 条提醒
    lines = [line for line in result.split("\n") if line.strip()]
    assert len(lines) <= 3


def test_no_reminder_when_first_speech():
    """speaker 第一次发言（没有 prior 消息），且其他变化也不存在 → 无 reminder。"""

    from core.chatroom_reminders import build_system_reminders

    room = {
        "messages": [],
        "members": ["planner"],
        "dynamic_members": [],
        "goal_history": [],
    }
    result = build_system_reminders(
        room, target_agent="planner", parent_message_id=None
    )
    assert result == ""
