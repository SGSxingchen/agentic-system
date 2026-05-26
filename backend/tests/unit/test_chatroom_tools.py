"""Phase 4 — chatroom autonomy tools 单测

覆盖范围:
- ContextVar 守卫：3 个工具在 chatroom 外调用直接 error
- chatroom_invite：成功路径 / 重名 / 总数超限 / allow_agent_invite=False / agent 未注册
- chatroom_create_agent：成功路径 / 重名 / 单 task 上限 2 / 总数超限 / base 不存在
- chatroom_set_goal：goal_history 推入 / 写 system 消息 / 广播事件
- _run_speaking_task 注入 workspace_root_override
- rebuild_chatroom_dynamic_agents：重启时按 spec 重建 Agent
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.agent.agent import Agent
from core.capability import CapabilityRegistry
from core.capability.agent_adapter import AgentCapability
from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import (
    TaskRegistry,
    set_current_create_counter,
    set_current_room_id,
    set_current_speaker_name,
    reset_current_create_counter,
    reset_current_room_id,
    reset_current_speaker_name,
)
from core.agent.registry import AgentRegistry


# ─── Mock LLM（够 Agent 构造，不会被实际调用）─────────────


class _StubLLM:
    async def chat(self, messages, tools=None):  # pragma: no cover - 不会跑
        return None

    async def chat_stream(self, messages, tools=None):  # pragma: no cover
        if False:
            yield None


# ─── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ChatroomStore:
    return ChatroomStore(root=tmp_path / "rooms")


@pytest.fixture
def cap_registry() -> CapabilityRegistry:
    return CapabilityRegistry()


@pytest.fixture
def agent_registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture(autouse=True)
def patch_dependencies(
    cap_registry: CapabilityRegistry,
    agent_registry: AgentRegistry,
    monkeypatch,
):
    """让工具内部的 _get_*_registry 指向 fixture 实例。"""

    monkeypatch.setattr(
        "capabilities.tools.chatroom_invite._get_capability_registry",
        lambda: cap_registry,
    )
    monkeypatch.setattr(
        "capabilities.tools.chatroom_invite._get_agent_registry",
        lambda: agent_registry,
    )
    monkeypatch.setattr(
        "capabilities.tools.chatroom_create_agent._get_capability_registry",
        lambda: cap_registry,
    )
    monkeypatch.setattr(
        "capabilities.tools.chatroom_create_agent._get_agent_registry",
        lambda: agent_registry,
    )

    async def _noop_broadcast(room_id, event_type, data):
        return None

    monkeypatch.setattr(
        "capabilities.tools.chatroom_invite._broadcast", _noop_broadcast
    )
    monkeypatch.setattr(
        "capabilities.tools.chatroom_create_agent._broadcast", _noop_broadcast
    )
    monkeypatch.setattr(
        "capabilities.tools.chatroom_set_goal._broadcast", _noop_broadcast
    )

    # 让 ChatroomStore() 默认指向 fixture 的临时 root（多次构造同根目录即可）
    yield


@pytest.fixture(autouse=True)
def patch_default_store(store: ChatroomStore, monkeypatch):
    """工具内部 ``ChatroomStore()`` 没传 root 时，让它落到 fixture root。"""

    monkeypatch.setenv("CHATROOMS_DIR", str(store.root))
    yield


def _make_room(store: ChatroomStore, **overrides: Any) -> Dict[str, Any]:
    defaults = dict(
        title="测试房间",
        topic="多 Agent 协作",
        members=["planner", "coder"],
    )
    defaults.update(overrides)
    return store.create_room(**defaults)


def _enter_room(room_id: str, speaker: str = "planner") -> tuple:
    """便利函数：把 ContextVar 推到 chatroom 状态，返回三元 token。"""

    room_token = set_current_room_id(room_id)
    speaker_token = set_current_speaker_name(speaker)
    counter_token = set_current_create_counter([0])
    return room_token, speaker_token, counter_token


def _exit_room(tokens: tuple) -> None:
    room_token, speaker_token, counter_token = tokens
    reset_current_create_counter(counter_token)
    reset_current_speaker_name(speaker_token)
    reset_current_room_id(room_token)


def _make_agent(name: str) -> Agent:
    return Agent(
        name=name,
        llm_client=_StubLLM(),
        system_prompt="dummy",
        tools=[],
    )


# ─── ContextVar 守卫 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_chatroom_invite_requires_room_context():
    from capabilities.tools.chatroom_invite import ChatroomInviteCapability

    tool = ChatroomInviteCapability()
    result = await tool.execute(agent_name="planner")
    assert "error" in result
    assert "chatroom" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_create_agent_requires_room_context():
    from capabilities.tools.chatroom_create_agent import ChatroomCreateAgentCapability

    tool = ChatroomCreateAgentCapability()
    result = await tool.execute(name="docs_writer", role_prompt="写文档")
    assert "error" in result
    assert "chatroom" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_set_goal_requires_room_context():
    from capabilities.tools.chatroom_set_goal import ChatroomSetGoalCapability

    tool = ChatroomSetGoalCapability()
    result = await tool.execute(goal="完成需求分析")
    assert "error" in result
    assert "chatroom" in result["error"].lower()


# ─── chatroom_invite ──────────────────────────────────────


@pytest.mark.asyncio
async def test_chatroom_invite_success(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_invite import ChatroomInviteCapability

    room = _make_room(store, members=["planner"])
    # 注册一个 reviewer Agent 进 registry（无须真实 LLM）
    agent_registry.register(_make_agent("reviewer"))

    tool = ChatroomInviteCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(agent_name="reviewer")
    finally:
        _exit_room(tokens)

    assert result.get("ok") is True
    assert result["agent_name"] == "reviewer"
    assert result["members_count"] == 2

    refreshed = store.get_room(room["id"])
    assert "reviewer" in refreshed["members"]
    sys_msgs = [m for m in refreshed["messages"] if m["sender"] == "system"]
    assert any("邀请 reviewer" in m["content"] for m in sys_msgs)


@pytest.mark.asyncio
async def test_chatroom_invite_rejects_already_in_room(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_invite import ChatroomInviteCapability

    room = _make_room(store, members=["planner", "coder"])
    agent_registry.register(_make_agent("coder"))

    tool = ChatroomInviteCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(agent_name="coder")
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "already" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_invite_rejects_when_disabled(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_invite import ChatroomInviteCapability

    room = _make_room(
        store,
        members=["planner"],
        settings={"allow_agent_invite": False},
    )
    agent_registry.register(_make_agent("reviewer"))

    tool = ChatroomInviteCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(agent_name="reviewer")
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "disallow" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_invite_rejects_unknown_agent(
    store: ChatroomStore,
):
    from capabilities.tools.chatroom_invite import ChatroomInviteCapability

    room = _make_room(store, members=["planner"])

    tool = ChatroomInviteCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(agent_name="ghost")
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "not registered" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_invite_rejects_when_member_limit_reached(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_invite import ChatroomInviteCapability

    # max_members=2，已有 2 名成员
    room = _make_room(
        store,
        members=["planner", "coder"],
        settings={"max_members": 2},
    )
    agent_registry.register(_make_agent("reviewer"))

    tool = ChatroomInviteCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(agent_name="reviewer")
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "limit" in result["error"].lower()


# ─── chatroom_create_agent ────────────────────────────────


@pytest.mark.asyncio
async def test_chatroom_create_agent_success(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import ChatroomCreateAgentCapability

    base = _make_agent("generic")
    agent_registry.register(base)
    room = _make_room(store, members=["planner"])

    tool = ChatroomCreateAgentCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(
            name="docs_writer",
            role_prompt="你负责写中文技术文档",
            base_agent="generic",
        )
    finally:
        _exit_room(tokens)

    assert result.get("ok") is True
    assert result["name"] == "docs_writer"
    assert agent_registry.get("docs_writer") is not None
    assert cap_registry.get("docs_writer") is not None

    refreshed = store.get_room(room["id"])
    assert "docs_writer" in refreshed["members"]
    dynamic_names = [m["name"] for m in refreshed["dynamic_members"]]
    assert "docs_writer" in dynamic_names


@pytest.mark.asyncio
async def test_chatroom_create_agent_rejects_duplicate_name(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import ChatroomCreateAgentCapability

    agent_registry.register(_make_agent("generic"))
    agent_registry.register(_make_agent("planner"))
    room = _make_room(store, members=["planner"])

    tool = ChatroomCreateAgentCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(
            name="planner",
            role_prompt="dup",
            base_agent="generic",
        )
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "already" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_create_agent_per_task_limit(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import ChatroomCreateAgentCapability

    agent_registry.register(_make_agent("generic"))
    room = _make_room(store, members=["planner"], settings={"max_members": 50})

    tool = ChatroomCreateAgentCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        r1 = await tool.execute(name="aa", role_prompt="a", base_agent="generic")
        r2 = await tool.execute(name="bb", role_prompt="b", base_agent="generic")
        r3 = await tool.execute(name="cc", role_prompt="c", base_agent="generic")
    finally:
        _exit_room(tokens)

    assert r1.get("ok") is True
    assert r2.get("ok") is True
    assert "error" in r3
    assert "limit" in r3["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_create_agent_member_limit(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import ChatroomCreateAgentCapability

    agent_registry.register(_make_agent("generic"))
    room = _make_room(
        store,
        members=["planner", "coder"],
        settings={"max_members": 2},
    )

    tool = ChatroomCreateAgentCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(
            name="docs_writer",
            role_prompt="x",
            base_agent="generic",
        )
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "limit" in result["error"].lower()


@pytest.mark.asyncio
async def test_chatroom_create_agent_missing_base_agent(
    store: ChatroomStore,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import ChatroomCreateAgentCapability

    room = _make_room(store, members=["planner"])

    tool = ChatroomCreateAgentCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(
            name="docs_writer",
            role_prompt="x",
            base_agent="ghost_agent",
        )
    finally:
        _exit_room(tokens)

    assert "error" in result
    assert "ghost_agent" in result["error"]


# ─── chatroom_set_goal ────────────────────────────────────


@pytest.mark.asyncio
async def test_chatroom_set_goal_pushes_history_and_writes_message(
    store: ChatroomStore,
):
    from capabilities.tools.chatroom_set_goal import ChatroomSetGoalCapability

    room = _make_room(store, members=["planner"], goal="原目标")

    tool = ChatroomSetGoalCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(goal="新目标 v2", reason="范围调整")
    finally:
        _exit_room(tokens)

    assert result.get("ok") is True
    refreshed = store.get_room(room["id"])
    assert refreshed["goal"] == "新目标 v2"
    assert refreshed["goal_history"]
    assert refreshed["goal_history"][-1]["goal"] == "原目标"
    assert refreshed["goal_history"][-1]["set_by"] == "planner"
    assert refreshed["goal_history"][-1]["reason"] == "范围调整"

    sys_msgs = [m for m in refreshed["messages"] if m["sender"] == "system"]
    assert any("新目标 v2" in m["content"] for m in sys_msgs)


@pytest.mark.asyncio
async def test_chatroom_set_goal_broadcasts_event(
    store: ChatroomStore,
    monkeypatch,
):
    from capabilities.tools import chatroom_set_goal as mod

    room = _make_room(store, members=["planner"])
    captured: List[Dict[str, Any]] = []

    async def _capture(room_id, event_type, data):
        captured.append({"room_id": room_id, "type": event_type, "data": data})

    monkeypatch.setattr(mod, "_broadcast", _capture)

    tool = mod.ChatroomSetGoalCapability()
    tokens = _enter_room(room["id"], "planner")
    try:
        result = await tool.execute(goal="aim")
    finally:
        _exit_room(tokens)

    assert result.get("ok") is True
    assert any(e["type"] == "chatroom_goal_updated" for e in captured)


# ─── _run_speaking_task workspace 注入 ─────────────────────


@pytest.mark.asyncio
async def test_run_speaking_task_sets_workspace_root_override(
    store: ChatroomStore,
    monkeypatch,
    tmp_path: Path,
):
    """验证 _run_speaking_task 能解析 workspace_id 并 set workspace_root_override。"""

    import types

    from core import chatroom_orchestrator as orch
    from core.task import get_workspace_root_override

    fake_root = tmp_path / "managed-workspace"
    fake_root.mkdir(parents=True, exist_ok=True)

    class FakeWorkspace:
        id = "ws-1"
        root_path = str(fake_root)

    class FakeStore:
        def __init__(self):
            pass

        def get(self, ws_id: str):
            assert ws_id == "ws-1"
            return FakeWorkspace()

    class FakeWorkspaceNotFoundError(KeyError):
        pass

    fake_module = types.ModuleType("core.workspace")
    fake_module.WorkspaceStore = FakeStore
    fake_module.WorkspaceNotFoundError = FakeWorkspaceNotFoundError
    monkeypatch.setitem(sys.modules, "core.workspace", fake_module)

    room = store.create_room(
        title="ws-room",
        topic="topic",
        members=["planner"],
        workspace_id="ws-1",
    )

    captured_root: Dict[str, Optional[Path]] = {"root": None}

    class CaptureCap(CapabilityBase):
        @property
        def name(self) -> str:
            return "planner"

        @property
        def description(self) -> str:
            return "capture root"

        def get_schema(self) -> CapabilitySchema:
            return CapabilitySchema(name="planner", description="capture")

        async def execute(self, **kwargs):
            return {"response": "ok"}

        async def execute_stream(self, **kwargs):
            captured_root["root"] = get_workspace_root_override()
            yield {"type": "done", "content": {"response": "ok"}}

    cap = CaptureCap()
    cap_reg = CapabilityRegistry()
    cap_reg.register_native(cap)
    task_reg = TaskRegistry()

    monkeypatch.setattr(orch, "_get_capability_registry", lambda: cap_reg)
    monkeypatch.setattr(orch, "_get_task_registry", lambda: task_reg)

    async def _noop(room_id, event_type, data):
        return None

    monkeypatch.setattr(orch, "_broadcast", _noop)

    ticket = orch.dispatch_speaking_task(
        room["id"], "planner", prompt="hi", store=store
    )
    background = task_reg._asyncio_tasks.get(ticket["task_id"])
    assert background is not None
    await asyncio.wait_for(background, timeout=2.0)

    assert captured_root["root"] == fake_root.resolve()


# ─── rebuild_chatroom_dynamic_agents ──────────────────────


def test_rebuild_chatroom_dynamic_agents_recreates_members(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import rebuild_chatroom_dynamic_agents

    # 准备：base agent 已注册，房间 JSON 里有 dynamic_members
    base = _make_agent("generic")
    agent_registry.register(base)

    room = store.create_room(
        title="restart-test",
        topic="t",
        members=["planner", "ghostly"],
        dynamic_members=[
            {"name": "ghostly", "role_prompt": "你是幽灵", "base_agent": "generic"}
        ],
    )

    # 重建前 ghostly 不在 registry
    assert agent_registry.get("ghostly") is None
    assert cap_registry.get("ghostly") is None

    rebuild_chatroom_dynamic_agents()

    assert agent_registry.get("ghostly") is not None
    assert cap_registry.get("ghostly") is not None


def test_rebuild_chatroom_dynamic_agents_skips_missing_base(
    store: ChatroomStore,
    cap_registry: CapabilityRegistry,
    agent_registry: AgentRegistry,
):
    from capabilities.tools.chatroom_create_agent import rebuild_chatroom_dynamic_agents

    # 只注册 planner，不注册 generic
    agent_registry.register(_make_agent("planner"))

    store.create_room(
        title="bad-base",
        topic="t",
        members=["planner", "phantom"],
        dynamic_members=[
            {"name": "phantom", "role_prompt": "x", "base_agent": "missing_base"}
        ],
    )

    # 不应抛错
    rebuild_chatroom_dynamic_agents()
    assert agent_registry.get("phantom") is None
