"""A27.A — ChatroomStore.add_message 严格单调递增 created_at。

确保同一房间内连续 add_message 时 created_at 严格递增（即使在同一毫秒内
快速连续写入也不会重复）。不同房间互不影响。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.chatroom import ChatroomStore


@pytest.fixture
def store(tmp_path):
    return ChatroomStore(root=tmp_path)


def _parse(ts: str) -> datetime:
    """解析 ISO8601，包含 +00:00 的时区。"""

    return datetime.fromisoformat(ts)


def test_consecutive_messages_have_strictly_monotonic_created_at(
    store: ChatroomStore,
):
    """同房间连续 add 5 条，断言 created_at 严格递增。"""

    room = store.create_room(title="A27 房间", members=["user", "agent:planner"])
    room_id = room["id"]

    messages = []
    for idx in range(5):
        msg = store.add_message(
            room_id,
            {"sender": "user", "content": f"msg-{idx}"},
        )
        assert msg is not None
        messages.append(msg)

    timestamps = [_parse(m["created_at"]) for m in messages]
    for i in range(1, len(timestamps)):
        assert timestamps[i] > timestamps[i - 1], (
            f"created_at 应严格递增：t[{i-1}]={timestamps[i-1]} "
            f"t[{i}]={timestamps[i]}"
        )


def test_monotonic_state_isolated_between_rooms(store: ChatroomStore):
    """不同房间各自维护单调时钟，互不影响。"""

    room_a = store.create_room(title="A", members=["x"])
    room_b = store.create_room(title="B", members=["y"])

    # 在 A 里连写 3 条，把 A 的 _last_message_time 推进
    for idx in range(3):
        store.add_message(room_a["id"], {"sender": "user", "content": f"a-{idx}"})

    # B 房间第一条消息不应被 A 的时钟影响
    msg_b = store.add_message(room_b["id"], {"sender": "user", "content": "b-0"})
    assert msg_b is not None

    # B 自己内部仍要严格递增
    msg_b2 = store.add_message(room_b["id"], {"sender": "user", "content": "b-1"})
    assert msg_b2 is not None
    assert _parse(msg_b2["created_at"]) > _parse(msg_b["created_at"])


def test_explicit_created_at_does_not_break_monotonic(store: ChatroomStore):
    """显式传入 created_at 时仍应被纳入单调时钟，下一条不能回退。"""

    room = store.create_room(title="C", members=["z"])
    room_id = room["id"]

    # 第一条用一个未来时间戳
    future_ts = "2099-01-01T00:00:00+00:00"
    msg1 = store.add_message(
        room_id,
        {"sender": "user", "content": "future", "created_at": future_ts},
    )
    assert msg1 is not None

    # 第二条不传 created_at（用 utcnow），应严格 > 第一条
    msg2 = store.add_message(
        room_id, {"sender": "user", "content": "now"}
    )
    assert msg2 is not None
    assert _parse(msg2["created_at"]) > _parse(msg1["created_at"])
