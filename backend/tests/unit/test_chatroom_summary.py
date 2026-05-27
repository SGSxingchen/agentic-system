"""Tests for chatroom summary trigger and writer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.chatroom import (
    ChatroomStore,
    should_summarize,
    summarize_room,
)
from core.llm.base import LLMResponse


class FakeLLM:
    def __init__(self, *, content: str = "summary block", raise_exc: Exception | None = None):
        self.calls: List[List[Dict[str, Any]]] = []
        self._content = content
        self._raise = raise_exc

    async def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        if self._raise is not None:
            raise self._raise
        return LLMResponse(content=self._content, stop_reason="end_turn")


@pytest.fixture
def store(tmp_path: Path) -> ChatroomStore:
    return ChatroomStore(root=tmp_path / "rooms")


def _seed(store: ChatroomStore, count: int, **room_overrides: Any) -> Dict[str, Any]:
    room = store.create_room(
        title="测试", members=["planner", "coder"], **room_overrides
    )
    for i in range(count):
        store.add_message(
            room["id"], {"sender": "user", "content": f"point {i}", "status": "done"}
        )
    return store.get_room(room["id"])


# ─── should_summarize ──────────────────────────────────────


def test_should_summarize_returns_false_when_below_threshold(store: ChatroomStore):
    room = _seed(store, count=3, settings={"recent_n": 2, "summary_threshold_m": 5})
    assert should_summarize(room) is False


def test_should_summarize_returns_true_when_threshold_met(store: ChatroomStore):
    # 3 条早于"最近 1 条"，阈值 = 2 → True
    room = _seed(store, count=4, settings={"recent_n": 1, "summary_threshold_m": 2})
    assert should_summarize(room) is True


def test_should_summarize_skips_messages_already_summarized(store: ChatroomStore):
    room = _seed(store, count=6, settings={"recent_n": 2, "summary_threshold_m": 3})
    # 提前把 cursor 推到第 3 条
    fresh = store.update_room(
        room["id"],
        summary="prev summary",
        summary_until_msg_id=room["messages"][2]["id"],
    )
    assert fresh is not None
    # 现在早于最近 2 的是 4 条，但 cursor 之后只剩 1 条 → 阈值 3 不满足
    assert should_summarize(fresh) is False


def test_should_summarize_handles_empty_room(store: ChatroomStore):
    empty = store.create_room(title="空", members=["x"])
    assert should_summarize(empty) is False


# ─── summarize_room ────────────────────────────────────────


@pytest.mark.asyncio
async def test_summarize_room_writes_back_summary(store: ChatroomStore):
    room = _seed(store, count=4, settings={"recent_n": 1, "summary_threshold_m": 2})
    llm = FakeLLM(content="提炼出来的摘要要点")

    updated = await summarize_room(room, llm, store=store)

    assert updated is not None
    assert updated["summary"] == "提炼出来的摘要要点"
    assert updated["summary_until_msg_id"]
    # cursor 应该指向"早于最近 1 条"窗口内的最后一条
    expected_id = room["messages"][-2]["id"]
    assert updated["summary_until_msg_id"] == expected_id

    # 确认确实落了盘
    on_disk = store.get_room(room["id"])
    assert on_disk["summary"] == "提炼出来的摘要要点"


@pytest.mark.asyncio
async def test_summarize_room_returns_none_when_no_candidates(store: ChatroomStore):
    room = _seed(store, count=2, settings={"recent_n": 5, "summary_threshold_m": 1})
    llm = FakeLLM()

    result = await summarize_room(room, llm, store=store)

    assert result is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_summarize_room_swallows_llm_failure(store: ChatroomStore):
    room = _seed(store, count=4, settings={"recent_n": 1, "summary_threshold_m": 2})
    llm = FakeLLM(raise_exc=RuntimeError("upstream timeout"))

    result = await summarize_room(room, llm, store=store)

    assert result is None
    on_disk = store.get_room(room["id"])
    assert on_disk["summary"] is None


@pytest.mark.asyncio
async def test_summarize_room_skips_when_no_llm_client(store: ChatroomStore):
    room = _seed(store, count=4, settings={"recent_n": 1, "summary_threshold_m": 2})
    assert await summarize_room(room, None, store=store) is None


@pytest.mark.asyncio
async def test_summarize_includes_previous_summary_in_prompt(store: ChatroomStore):
    room = _seed(store, count=5, settings={"recent_n": 1, "summary_threshold_m": 2})
    store.update_room(
        room["id"], summary="之前的简要", summary_until_msg_id=room["messages"][0]["id"]
    )
    refreshed = store.get_room(room["id"])
    llm = FakeLLM(content="并入更新后的摘要")

    updated = await summarize_room(refreshed, llm, store=store)

    assert updated is not None
    assert updated["summary"] == "并入更新后的摘要"
    user_block = llm.calls[0][1]["content"]
    assert "已有摘要" in user_block
    assert "之前的简要" in user_block
    assert "新增对话" in user_block
