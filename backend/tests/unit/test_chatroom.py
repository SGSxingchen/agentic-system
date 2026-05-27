"""Unit tests for ``core.chatroom`` (Phase 1 backend skeleton)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Same convention as the other unit tests: prepend ``backend/src``.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.chatroom import (
    DEFAULT_SETTINGS,
    ChatroomStore,
    build_room_context,
    parse_mentions,
)


# ─── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return ChatroomStore(root=tmp_path)


# ─── Store CRUD ───────────────────────────────────────────


def test_create_and_get_room(store: ChatroomStore):
    room = store.create_room(
        title="毕设组",
        topic="基于多智能体协作的自动化代码生成",
        goal="完成 Phase 1 后端骨架",
        members=["planner", "coder"],
        workspace_id="ws-123",
    )

    assert room["id"]
    assert room["title"] == "毕设组"
    assert room["goal"] == "完成 Phase 1 后端骨架"
    assert room["members"] == ["planner", "coder"]
    assert room["workspace_id"] == "ws-123"
    # default settings merged
    for key in DEFAULT_SETTINGS:
        assert key in room["settings"]
    assert room["messages"] == []

    fetched = store.get_room(room["id"])
    assert fetched is not None
    assert fetched["id"] == room["id"]
    assert fetched["members"] == ["planner", "coder"]


def test_list_rooms_sorted_by_updated_at(store: ChatroomStore):
    a = store.create_room(title="A", members=["x"])
    b = store.create_room(title="B", members=["y"])
    # Bumping room A makes it the freshest entry.
    store.update_room(a["id"], goal="bump")

    summaries = store.list_rooms()
    assert [s["id"] for s in summaries[:2]] == [a["id"], b["id"]]
    assert summaries[0]["title"] == "A"
    assert summaries[0]["goal"] == "bump"
    assert summaries[0]["message_count"] == 0


def test_update_and_delete_room(store: ChatroomStore):
    room = store.create_room(title="X", members=["planner"])
    updated = store.update_room(
        room["id"],
        title="X2",
        settings={"recent_n": 5},
    )
    assert updated is not None
    assert updated["title"] == "X2"
    # settings merge — defaults kept
    assert updated["settings"]["recent_n"] == 5
    assert updated["settings"]["host_agent"] == DEFAULT_SETTINGS["host_agent"]

    assert store.delete_room(room["id"]) is True
    assert store.get_room(room["id"]) is None
    assert store.delete_room(room["id"]) is False


def test_add_messages_keep_order(store: ChatroomStore):
    room = store.create_room(title="顺序测试", members=["planner", "coder"])
    for i in range(10):
        store.add_message(
            room["id"],
            {
                "sender": "user" if i % 2 == 0 else "agent:planner",
                "content": f"msg-{i}",
                "status": "done",
            },
        )

    messages = store.list_messages(room["id"])
    assert [m["content"] for m in messages] == [f"msg-{i}" for i in range(10)]


def test_list_messages_since(store: ChatroomStore):
    room = store.create_room(title="since-test", members=["planner"])
    ids = []
    for i in range(5):
        msg = store.add_message(
            room["id"],
            {"sender": "user", "content": f"m{i}", "status": "done"},
        )
        ids.append(msg["id"])

    rest = store.list_messages(room["id"], since=ids[1])
    assert [m["content"] for m in rest] == ["m2", "m3", "m4"]


def test_update_message(store: ChatroomStore):
    room = store.create_room(title="update", members=["planner"])
    pending = store.add_message(
        room["id"],
        {
            "sender": "agent:planner",
            "content": "",
            "status": "pending",
        },
    )

    final = store.update_message(
        room["id"],
        pending["id"],
        content="hello world",
        status="done",
        meta={"tokens": 42},
    )
    assert final is not None
    assert final["content"] == "hello world"
    assert final["status"] == "done"
    assert final["meta"]["tokens"] == 42


def test_json_persistence_roundtrip(tmp_path):
    a = ChatroomStore(root=tmp_path)
    room = a.create_room(
        title="持久化测试",
        topic="round-trip",
        goal="保留所有字段",
        members=["planner", "coder"],
        dynamic_members=[
            {"name": "writer", "role_prompt": "写文档", "base_agent": "generic"}
        ],
        workspace_id="ws-1",
        settings={"recent_n": 7},
    )
    a.add_message(
        room["id"],
        {"sender": "user", "content": "@planner 走起", "status": "done"},
    )

    # Verify file layout (one file per room + index)
    room_path = tmp_path / f"{room['id']}.json"
    index_path = tmp_path / "_index.json"
    assert room_path.exists()
    assert index_path.exists()

    raw = json.loads(room_path.read_text(encoding="utf-8"))
    assert raw["id"] == room["id"]
    assert raw["dynamic_members"][0]["name"] == "writer"

    # New store instance must read the same data.
    b = ChatroomStore(root=tmp_path)
    fresh = b.get_room(room["id"])
    assert fresh is not None
    assert fresh["title"] == "持久化测试"
    assert fresh["dynamic_members"][0]["role_prompt"] == "写文档"
    assert fresh["settings"]["recent_n"] == 7
    assert len(fresh["messages"]) == 1
    assert fresh["messages"][0]["content"] == "@planner 走起"


# ─── Mention parser ───────────────────────────────────────


def test_parse_mentions_basic_and_unicode():
    valid = ["planner", "coder", "审稿人", "doc_writer-1"]
    text = "@planner 来 @审稿人 看一下，再让 @doc_writer-1 改文档"
    assert parse_mentions(text, valid) == ["planner", "审稿人", "doc_writer-1"]


def test_parse_mentions_dedupe_in_order():
    valid = ["planner", "coder"]
    text = "@coder @planner @coder 再看看 @planner"
    assert parse_mentions(text, valid) == ["coder", "planner"]


def test_parse_mentions_unknown_filtered():
    valid = ["planner"]
    assert parse_mentions("@planner @stranger @ghost", valid) == ["planner"]


def test_parse_mentions_double_at_escaped():
    valid = ["planner"]
    # @@ → literal @, should NOT trigger a mention
    assert parse_mentions("发邮件给 user@@planner.com", valid) == []
    # 转义字符在前，后面再写一次正常 @planner 仍然算
    assert parse_mentions("user@@example 然后 @planner", valid) == ["planner"]


def test_parse_mentions_skips_inline_code():
    valid = ["planner", "coder"]
    text = "示例代码 `@planner` 不应被识别，但正文里 @coder 算"
    assert parse_mentions(text, valid) == ["coder"]


def test_parse_mentions_skips_code_block():
    valid = ["planner", "coder"]
    text = (
        "```python\n"
        "# @planner 这里在代码里\n"
        "print('hi')\n"
        "```\n"
        "@coder 这里在外面"
    )
    assert parse_mentions(text, valid) == ["coder"]


def test_parse_mentions_consecutive_and_punctuation():
    valid = ["planner", "coder"]
    text = "@planner，@coder！再把任务交给 @planner 处理"
    assert parse_mentions(text, valid) == ["planner", "coder"]


# ─── Context builder ──────────────────────────────────────


def _make_room_with_messages(store: ChatroomStore):
    room = store.create_room(
        title="context",
        topic="主题文本",
        goal="目标-A",
        members=["planner", "coder"],
    )
    # 3 done + 1 pending + 1 system + 1 done at the end
    store.add_message(
        room["id"], {"sender": "user", "content": "你好 @planner", "status": "done"}
    )
    store.add_message(
        room["id"],
        {"sender": "agent:planner", "content": "好的，我来安排", "status": "done"},
    )
    store.add_message(
        room["id"],
        {"sender": "agent:coder", "content": "我准备实现", "status": "done"},
    )
    store.add_message(
        room["id"],
        {"sender": "agent:planner", "content": "WIP", "status": "pending"},
    )
    store.add_message(
        room["id"], {"sender": "system", "content": "目标已更新", "status": "done"}
    )
    store.add_message(
        room["id"], {"sender": "user", "content": "继续吧", "status": "done"}
    )
    return store.get_room(room["id"])


def test_build_room_context_system_block_layout(store: ChatroomStore):
    room = _make_room_with_messages(store)
    messages = build_room_context(room, "planner", recent_n=10)

    assert messages[0]["role"] == "system"
    sys_text = messages[0]["content"]
    # Order matters: topic → goal → summary → 当前任务
    topic_idx = sys_text.index("[房间主题]")
    goal_idx = sys_text.index("[当前主要目标]")
    summary_idx = sys_text.index("[房间背景摘要]")
    task_idx = sys_text.index("[当前任务]")
    assert topic_idx < goal_idx < summary_idx < task_idx
    assert "主题文本" in sys_text
    assert "目标-A" in sys_text
    assert "（暂无摘要）" in sys_text
    assert "你是群聊成员 planner" in sys_text
    # 其他成员里应该出现 coder，不应包含自己
    assert "coder" in sys_text


def test_build_room_context_skips_pending_and_prefixes_others(store: ChatroomStore):
    room = _make_room_with_messages(store)
    messages = build_room_context(room, "planner", recent_n=20)

    contents = [m["content"] for m in messages[1:]]
    # pending 消息内容 "WIP" 不应出现
    assert all("WIP" not in c for c in contents)

    # 自己的发言 (sender=agent:planner, "好的，我来安排") 不应带 [planner]: 前缀
    assert any(c == "好的，我来安排" for c in contents)
    # coder 的发言要带 [coder]: 前缀
    assert any(c == "[coder]: 我准备实现" for c in contents)
    # system 消息走 user 角色 + [system]: 前缀
    assert any(c.startswith("[system]:") for c in contents)


def test_build_room_context_recent_n_truncates(store: ChatroomStore):
    room = store.create_room(title="N", members=["planner"])
    for i in range(15):
        store.add_message(
            room["id"],
            {"sender": "user", "content": f"u{i}", "status": "done"},
        )
    full_room = store.get_room(room["id"])

    messages = build_room_context(full_room, "planner", recent_n=5)
    history = messages[1:]
    assert len(history) == 5
    assert [m["content"] for m in history] == [f"u{i}" for i in range(10, 15)]


def test_build_room_context_uses_settings_recent_n_by_default(store: ChatroomStore):
    room = store.create_room(
        title="settings",
        members=["planner"],
        settings={"recent_n": 2},
    )
    for i in range(6):
        store.add_message(
            room["id"],
            {"sender": "user", "content": f"u{i}", "status": "done"},
        )
    full_room = store.get_room(room["id"])

    messages = build_room_context(full_room, "planner")
    history = messages[1:]
    assert [m["content"] for m in history] == ["u4", "u5"]


def test_build_room_context_dynamic_members_in_others(store: ChatroomStore):
    room = store.create_room(
        title="dynamic",
        members=["planner"],
        dynamic_members=[
            {"name": "writer", "role_prompt": "写文档", "base_agent": "generic"}
        ],
    )
    full_room = store.get_room(room["id"])

    messages = build_room_context(full_room, "planner")
    sys_text = messages[0]["content"]
    assert "writer" in sys_text
    # planner 是 target，不应在 others 里
    other_section = sys_text.split("其他成员：", 1)[1]
    assert "planner" not in other_section


# ─── 回归测试：未闭合代码块 ──────────────────────────────


def test_parse_mentions_skips_unclosed_triple_backtick():
    """未闭合的 ``` 代码块也应跳过其后的 @ — Phase 4 review 修复。"""

    text = "前导 @planner\n```python\nx = '@coder ignored from here on'"
    assert parse_mentions(text, ["planner", "coder"]) == ["planner"]


def test_parse_mentions_skips_unclosed_inline_backtick():
    """未闭合的行内 ` 后的 @ 也应被忽略，至到行尾。"""

    text = "看这个 @planner ，但是这个 `不闭合 @coder 也不算"
    assert parse_mentions(text, ["planner", "coder"]) == ["planner"]
