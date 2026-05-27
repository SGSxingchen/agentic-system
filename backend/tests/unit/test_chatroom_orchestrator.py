"""Unit tests for the chatroom speaking-task scheduler (Phase 2)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import patch

import pytest

# 与其他单测一致：把 backend/src 注入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.capability import CapabilityRegistry
from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.chatroom_orchestrator import (
    dispatch_speaking_task,
    maybe_schedule_summary,
    _build_memory_query,
    _relay_depth,
)
from core.task import TaskRegistry, TaskStatus, TaskType


# ─── Mock 工具 ─────────────────────────────────────────────


class StreamingEchoCapability(CapabilityBase):
    """流式 capability：返回固定脚本的事件流。"""

    def __init__(
        self,
        name: str,
        events: Optional[List[Dict[str, Any]]] = None,
        *,
        sleep: float = 0.0,
    ) -> None:
        super().__init__()
        self._name = name
        self._events = events or [
            {"type": "thinking", "content": f"hello from {name}"},
            {"type": "done", "content": {"response": f"finished {name}"}},
        ]
        self._sleep = sleep
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def description(self) -> str:  # type: ignore[override]
        return f"echo {self._name}"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self._name, description=self.description)

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        return {"response": f"finished {self._name}"}

    async def execute_stream(self, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
        self.calls.append(dict(kwargs))
        for event in self._events:
            if self._sleep:
                await asyncio.sleep(self._sleep)
            yield dict(event)


class HangingCapability(CapabilityBase):
    """流到一半就 sleep，便于测试取消。"""

    def __init__(self, name: str = "planner") -> None:
        super().__init__()
        self._name = name
        self.cancelled = False

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def description(self) -> str:  # type: ignore[override]
        return "hanging echo"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self._name, description=self.description)

    async def execute(self, **kwargs: Any) -> Any:
        return {"response": "ok"}

    async def execute_stream(self, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
        try:
            yield {"type": "thinking", "content": "starting"}
            await asyncio.sleep(5.0)
            yield {"type": "done", "content": {"response": "ok"}}
        except asyncio.CancelledError:
            self.cancelled = True
            raise


# ─── 公共 fixtures ─────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ChatroomStore:
    return ChatroomStore(root=tmp_path / "rooms")


@pytest.fixture
def cap_registry() -> CapabilityRegistry:
    return CapabilityRegistry()


@pytest.fixture
def task_registry() -> TaskRegistry:
    return TaskRegistry()


@pytest.fixture(autouse=True)
def patch_dependencies(cap_registry: CapabilityRegistry, task_registry: TaskRegistry, monkeypatch):
    """让 orchestrator 的 _get_*_registry 帮我们指向 fixture 实例。"""

    monkeypatch.setattr(
        "core.chatroom_orchestrator._get_capability_registry",
        lambda: cap_registry,
    )
    monkeypatch.setattr(
        "core.chatroom_orchestrator._get_task_registry",
        lambda: task_registry,
    )

    async def _noop_broadcast(room_id, event_type, data):
        return None

    monkeypatch.setattr("core.chatroom_orchestrator._broadcast", _noop_broadcast)
    yield


def _make_room(store: ChatroomStore, **overrides: Any) -> Dict[str, Any]:
    defaults = dict(
        title="测试房间",
        topic="多 Agent 协作",
        members=["planner", "coder"],
    )
    defaults.update(overrides)
    return store.create_room(**defaults)


# ─── 校验失败路径 ──────────────────────────────────────────


def test_dispatch_unknown_room_returns_error(store: ChatroomStore):
    ticket = dispatch_speaking_task("does-not-exist", "planner", store=store)
    assert ticket["task_id"] is None
    assert ticket["error"] == "chatroom_not_found"


def test_dispatch_member_not_in_room_writes_failed_message(store: ChatroomStore):
    room = _make_room(store)

    ticket = dispatch_speaking_task(room["id"], "stranger", store=store)

    assert ticket["task_id"] is None
    assert ticket["error"] == "member_not_in_room"
    assert ticket["message_id"]

    fetched = store.get_room(room["id"])
    assert fetched is not None
    assert len(fetched["messages"]) == 1
    only = fetched["messages"][0]
    assert only["sender"] == "agent:stranger"
    assert only["status"] == "failed"
    assert only["meta"].get("error") == "member_not_in_room"


def test_dispatch_agent_not_registered_writes_failed_message(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
):
    # cap_registry 故意不注册 planner
    room = _make_room(store, members=["planner"])

    ticket = dispatch_speaking_task(room["id"], "planner", store=store)

    assert ticket["task_id"] is None
    assert ticket["error"] == "agent_not_registered"
    assert ticket["message_id"]

    fetched = store.get_room(room["id"])
    assert fetched is not None
    assert fetched["messages"][0]["status"] == "failed"
    assert fetched["messages"][0]["meta"].get("error") == "agent_not_registered"


def test_relay_depth_helper_counts_only_agent_chain(store: ChatroomStore):
    room = _make_room(store)
    user_msg = store.add_message(
        room["id"],
        {"sender": "user", "content": "hi @planner", "status": "done"},
    )
    a1 = store.add_message(
        room["id"],
        {
            "sender": "agent:planner",
            "content": "@coder",
            "status": "done",
            "parent_message_id": user_msg["id"],
        },
    )
    a2 = store.add_message(
        room["id"],
        {
            "sender": "agent:coder",
            "content": "@planner",
            "status": "done",
            "parent_message_id": a1["id"],
        },
    )

    refreshed = store.get_room(room["id"])
    msgs = refreshed["messages"]

    assert _relay_depth(msgs, parent_message_id=None) == 0
    assert _relay_depth(msgs, parent_message_id=user_msg["id"]) == 0
    assert _relay_depth(msgs, parent_message_id=a1["id"]) == 1
    assert _relay_depth(msgs, parent_message_id=a2["id"]) == 2


# ─── _build_memory_query (A1) ─────────────────────────────


def test_build_memory_query_takes_last_three_messages():
    room = {
        "messages": [
            {"sender": "user", "content": "old"},
            {"sender": "user", "content": "msg1"},
            {"sender": "agent:assistant", "content": "msg2"},
            {"sender": "user", "content": "msg3"},
        ],
    }
    query = _build_memory_query(room, prompt="follow up")
    assert "msg1" in query
    assert "msg2" in query
    assert "msg3" in query
    assert "old" not in query
    assert "follow up" in query.splitlines()[-1]


def test_build_memory_query_skips_blank_messages():
    room = {
        "messages": [
            {"sender": "user", "content": "  "},
            {"sender": "user", "content": "real"},
        ]
    }
    query = _build_memory_query(room, prompt=None)
    assert query.count("\n") == 0  # 单行
    assert "real" in query


def test_build_memory_query_handles_empty():
    assert _build_memory_query({"messages": []}, None) == ""
    assert _build_memory_query({}, None) == ""


def test_dispatch_blocks_when_relay_depth_exceeded(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
):
    cap_registry.register_native(StreamingEchoCapability("planner"))
    room = _make_room(
        store,
        settings={"max_relay_depth": 2},
    )
    user_msg = store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )
    a1 = store.add_message(
        room["id"],
        {
            "sender": "agent:planner",
            "content": "step1",
            "status": "done",
            "parent_message_id": user_msg["id"],
        },
    )
    a2 = store.add_message(
        room["id"],
        {
            "sender": "agent:planner",
            "content": "step2",
            "status": "done",
            "parent_message_id": a1["id"],
        },
    )

    ticket = dispatch_speaking_task(
        room["id"],
        "planner",
        parent_message_id=a2["id"],
        store=store,
    )

    assert ticket["task_id"] is None
    assert ticket["skipped"] == "max_relay_depth"

    refreshed = store.get_room(room["id"])
    last = refreshed["messages"][-1]
    assert last["sender"] == "system"
    assert "已达接力上限" in last["content"]


# ─── 正常路径 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_normal_path_runs_capability(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
):
    cap = StreamingEchoCapability("planner")
    cap_registry.register_native(cap)
    room = _make_room(store, members=["planner"])

    ticket = dispatch_speaking_task(room["id"], "planner", prompt="say hi", store=store)
    assert ticket["task_id"] is not None
    assert ticket["message_id"]

    # 等待后台 task 跑完
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await background

    state = task_registry.get(ticket["task_id"])
    assert state is not None
    assert state.status is TaskStatus.COMPLETED
    assert state.type is TaskType.AGENT_SPEAK
    assert cap.calls, "capability should have been invoked"

    refreshed = store.get_room(room["id"])
    msg = next(m for m in refreshed["messages"] if m["id"] == ticket["message_id"])
    assert msg["status"] == "done"
    assert msg["content"] == "finished planner"
    assert msg["task_id"] == ticket["task_id"]


@pytest.mark.asyncio
async def test_dispatch_relays_to_mentioned_agent(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
):
    cap_registry.register_native(
        StreamingEchoCapability(
            "planner",
            events=[
                {"type": "thinking", "content": "let me ping coder"},
                {
                    "type": "done",
                    "content": {"response": "请 @coder 接手编码"},
                },
            ],
        )
    )
    cap_registry.register_native(
        StreamingEchoCapability(
            "coder",
            events=[
                {"type": "done", "content": {"response": "好的，已收到"}},
            ],
        )
    )
    room = _make_room(store, members=["planner", "coder"])

    ticket = dispatch_speaking_task(room["id"], "planner", prompt="kick off", store=store)
    assert ticket["task_id"] is not None

    # 第一个 task 跑完 → 接力 task 被创建 → 等所有后台 task 终态
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
        all_done = all(
            t.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED}
            for t in task_registry.list()
        )
        if all_done and len(task_registry.list()) >= 2:
            break

    states = task_registry.list()
    assert len(states) >= 2, "relay should have produced a second task"
    assert all(s.status is TaskStatus.COMPLETED for s in states)

    refreshed = store.get_room(room["id"])
    senders = [m["sender"] for m in refreshed["messages"]]
    assert "agent:planner" in senders
    assert "agent:coder" in senders


@pytest.mark.asyncio
async def test_dispatch_failure_marks_message_failed(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
):
    class BoomCap(CapabilityBase):
        @property
        def name(self) -> str:  # type: ignore[override]
            return "planner"

        @property
        def description(self) -> str:  # type: ignore[override]
            return "boom"

        def get_schema(self):
            return CapabilitySchema(name="planner", description="boom")

        async def execute(self, **kwargs):
            raise RuntimeError("kaboom")

        async def execute_stream(self, **kwargs):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover — make this an async generator

    cap_registry.register_native(BoomCap())
    room = _make_room(store, members=["planner"])

    ticket = dispatch_speaking_task(room["id"], "planner", store=store)
    assert ticket["task_id"]

    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    state = task_registry.get(ticket["task_id"])
    assert state is not None
    assert state.status is TaskStatus.FAILED
    assert "kaboom" in (state.error or "")

    refreshed = store.get_room(room["id"])
    msg = next(m for m in refreshed["messages"] if m["id"] == ticket["message_id"])
    assert msg["status"] == "failed"
    assert "kaboom" in msg["content"]


@pytest.mark.asyncio
async def test_dispatch_cancellation_marks_message_failed(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
):
    cap = HangingCapability("planner")
    cap_registry.register_native(cap)
    room = _make_room(store, members=["planner"])

    ticket = dispatch_speaking_task(room["id"], "planner", store=store)
    assert ticket["task_id"]
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None

    # 等 streaming 启动后再 kill
    for _ in range(20):
        await asyncio.sleep(0.05)
        snapshot = store.get_room(room["id"])
        msg = next(m for m in snapshot["messages"] if m["id"] == ticket["message_id"])
        if msg["status"] == "streaming":
            break

    task_registry.kill(ticket["task_id"])
    with pytest.raises(asyncio.CancelledError):
        await background

    state = task_registry.get(ticket["task_id"])
    assert state is not None
    assert state.status is TaskStatus.KILLED

    refreshed = store.get_room(room["id"])
    msg = next(m for m in refreshed["messages"] if m["id"] == ticket["message_id"])
    assert msg["status"] == "failed"
    assert msg["meta"].get("error") == "cancelled"
    assert cap.cancelled is True


# ─── A1: memory_context 注入 ───────────────────────────────


@pytest.mark.asyncio
async def test_run_speaking_task_injects_memory_context_when_auto_memory_true(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
    monkeypatch,
):
    cap = StreamingEchoCapability("assistant")
    cap_registry.register_native(cap)

    async def fake_build(query, *args, **kwargs):
        return ("[mem] foo bar", 1)

    monkeypatch.setattr(
        "api.websocket.handlers.build_memory_context",
        fake_build,
    )

    room = _make_room(store, members=["assistant"])
    store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )

    ticket = dispatch_speaking_task(room["id"], "assistant", store=store)
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    assert cap.calls, "capability 应被调用"
    assert cap.calls[0].get("memory_context") == "[mem] foo bar"


@pytest.mark.asyncio
async def test_run_speaking_task_skips_memory_when_auto_memory_false(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
    monkeypatch,
):
    cap = StreamingEchoCapability("assistant")
    cap_registry.register_native(cap)

    called: list[str] = []

    async def spy(query, *args, **kwargs):
        called.append(query)
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", spy)

    room = _make_room(
        store,
        members=["assistant"],
        settings={"auto_memory": False},
    )
    store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )

    ticket = dispatch_speaking_task(room["id"], "assistant", store=store)
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    assert called == [], "auto_memory=False 时不应调 build_memory_context"
    assert "memory_context" not in cap.calls[0]


@pytest.mark.asyncio
async def test_run_speaking_task_schedules_reflection_on_done(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
    monkeypatch,
):
    cap = StreamingEchoCapability("assistant")
    cap_registry.register_native(cap)

    async def fake_build(query, *args, **kwargs):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)

    calls: list[dict] = []

    def spy_reflect(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(
        "api.websocket.handlers.schedule_memory_reflection", spy_reflect
    )

    room = _make_room(store, members=["assistant"])
    store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )

    ticket = dispatch_speaking_task(room["id"], "assistant", store=store)
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    assert len(calls) == 1
    assert calls[0]["session_id"] == f"chatroom:{room['id']}"
    assert calls[0]["source"] == "chatroom:assistant"
    assert calls[0]["assistant_text"]


@pytest.mark.asyncio
async def test_run_speaking_task_skips_reflection_when_auto_memory_false(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
    monkeypatch,
):
    cap = StreamingEchoCapability("assistant")
    cap_registry.register_native(cap)

    async def fake_build(query, *args, **kwargs):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)

    calls: list[dict] = []
    monkeypatch.setattr(
        "api.websocket.handlers.schedule_memory_reflection",
        lambda **kw: calls.append(kw) or None,
    )

    room = _make_room(
        store,
        members=["assistant"],
        settings={"auto_memory": False},
    )
    store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )

    ticket = dispatch_speaking_task(room["id"], "assistant", store=store)
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    assert calls == []


# ─── A2: 闲聊文本契约覆盖 ──────────────────────────────────


@pytest.mark.asyncio
async def test_run_speaking_task_forces_output_format_text(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
    monkeypatch,
):
    """A2 (a)：payload 强制 output_format=text（防御性，留口子待 capability
    支持 input override 时生效）。当前 Agent 实现仅在构造时读 output_format，
    所以这条字段对真实 Agent 无效，真正起作用的是 (b) system 块覆盖。"""

    cap = StreamingEchoCapability("reviewer")
    cap_registry.register_native(cap)

    async def fake_build(query, *args, **kwargs):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)
    monkeypatch.setattr(
        "api.websocket.handlers.schedule_memory_reflection",
        lambda **kw: None,
    )

    room = _make_room(store, members=["reviewer"])
    store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )

    ticket = dispatch_speaking_task(room["id"], "reviewer", store=store)
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    assert cap.calls, "capability 应被调用"
    assert cap.calls[0].get("output_format") == "text"


@pytest.mark.asyncio
async def test_run_speaking_task_inserts_chatroom_override_system(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    task_registry: TaskRegistry,
    monkeypatch,
):
    """Spec 2 §6 / Task 4：聊天室协作模式现在通过 build_room_context 的 XML
    system 块直接嵌入（<protocol>），不再单独 messages.insert(0, ...)。
    要求 messages[0] 是 <chatroom_context> XML 块且内含 [聊天室协作模式]。"""

    cap = StreamingEchoCapability("reviewer")
    cap_registry.register_native(cap)

    async def fake_build(query, *args, **kwargs):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)
    monkeypatch.setattr(
        "api.websocket.handlers.schedule_memory_reflection",
        lambda **kw: None,
    )

    room = _make_room(store, members=["reviewer"])
    store.add_message(
        room["id"], {"sender": "user", "content": "hi", "status": "done"}
    )

    ticket = dispatch_speaking_task(room["id"], "reviewer", store=store)
    background = task_registry._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    msgs = cap.calls[0]["messages"]
    assert msgs[0]["role"] == "system"
    sys0 = msgs[0]["content"]
    # 一条 XML 化的 chatroom_context 块包含协议
    assert "<chatroom_context>" in sys0
    assert "[聊天室协作模式]" in sys0


# ─── 摘要触发 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_schedule_summary_skips_when_threshold_not_met(
    store: ChatroomStore,
    monkeypatch,
):
    room = _make_room(
        store,
        settings={"recent_n": 1, "summary_threshold_m": 5},
    )
    for i in range(2):
        store.add_message(room["id"], {"sender": "user", "content": f"q{i}", "status": "done"})

    called = {"value": False}

    class FakeLLM:
        async def chat(self, messages, tools=None):  # pragma: no cover
            called["value"] = True
            from core.llm.base import LLMResponse

            return LLMResponse(content="summary", stop_reason="end_turn")

    monkeypatch.setattr("core.chatroom_orchestrator._get_llm_client", lambda: FakeLLM())

    task = maybe_schedule_summary(room["id"], store=store)
    assert task is None
    assert not called["value"]


@pytest.mark.asyncio
async def test_maybe_schedule_summary_dispatches_background_task(
    store: ChatroomStore,
    monkeypatch,
):
    room = _make_room(
        store,
        settings={"recent_n": 1, "summary_threshold_m": 2},
    )
    for i in range(5):
        store.add_message(
            room["id"],
            {"sender": "user", "content": f"point {i}", "status": "done"},
        )

    from core.llm.base import LLMResponse

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            return LLMResponse(content="summary one-line", stop_reason="end_turn")

    fake = FakeLLM()
    monkeypatch.setattr("core.chatroom_orchestrator._get_llm_client", lambda: fake)

    task = maybe_schedule_summary(room["id"], store=store)
    assert task is not None
    await task

    refreshed = store.get_room(room["id"])
    assert refreshed["summary"] == "summary one-line"
    assert refreshed["summary_until_msg_id"]
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_dispatch_invalidates_disconnected_llm_gracefully(
    store: ChatroomStore,
    monkeypatch,
):
    room = _make_room(
        store,
        settings={"recent_n": 1, "summary_threshold_m": 2},
    )
    for i in range(5):
        store.add_message(
            room["id"], {"sender": "user", "content": f"x{i}", "status": "done"}
        )

    monkeypatch.setattr("core.chatroom_orchestrator._get_llm_client", lambda: None)
    assert maybe_schedule_summary(room["id"], store=store) is None


# =====================
# host_directive 解析（spec §3.4 完整版）
# =====================


def test_legacy_host_directive_parser_removed():
    """Task 8 — 文本协议被删除：_parse_host_directive / _extract_json_object 不再存在。"""

    import importlib

    m = importlib.import_module("core.chatroom_orchestrator")
    assert not hasattr(m, "_parse_host_directive"), (
        "Task 8 should have deleted _parse_host_directive"
    )
    assert not hasattr(m, "_extract_json_object"), (
        "Task 8 should have deleted _extract_json_object"
    )


def test_routes_chatrooms_no_host_prompt_injection():
    """routes/chatrooms.py 不应再注入 actions JSON 协议提示。"""

    import inspect
    from api.routes import chatrooms as chatrooms_route

    source = inspect.getsource(chatrooms_route)
    assert '"actions": [{"agent"' not in source, (
        "host_directive prompt injection should be deleted"
    )


def test_chatroom_payload_includes_new_autonomy_tools():
    """Task 10 — _CHATROOM_AUTONOMY_TOOLS 必须列出 dispatch/get_goal/update_goal/todo。

    chatroom_todo 在 Task 11 加入；本 task 只检查前 3 个，todo 用 xfail。
    """

    from api.main import _CHATROOM_AUTONOMY_TOOLS

    expected = {"chatroom_get_goal", "chatroom_update_goal", "chatroom_dispatch"}
    actual = set(_CHATROOM_AUTONOMY_TOOLS)
    missing = expected - actual
    assert not missing, f"missing autonomy tools: {missing}"


@pytest.mark.xfail(
    strict=True,
    reason="chatroom_todo added in Task 11; remove xfail once landed",
)
def test_chatroom_payload_includes_todo_tool():
    from api.main import _CHATROOM_AUTONOMY_TOOLS

    assert "chatroom_todo" in _CHATROOM_AUTONOMY_TOOLS
