"""dispatch_agent 单测（v2 Phase C 支柱 4）"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.agent import Agent
from core.capability import CapabilityRegistry
from core.capability.base import CapabilityBase, CapabilitySchema
from core.llm.base import BaseLLMClient, LLMResponse, ToolCall
from core.task import (
    TaskRegistry,
    TaskStatus,
    set_dispatch_depth,
    reset_dispatch_depth,
    set_parent_task_id,
    reset_parent_task_id,
)


# =====================
# Mock 工具
# =====================


class ScriptedLLM(BaseLLMClient):
    def __init__(self, responses: List[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: List[List[Dict[str, Any]]] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        if not self._responses:
            return LLMResponse(content="(exhausted)", stop_reason="end_turn")
        return self._responses.pop(0)


def _tool_use(tool_calls: List[ToolCall]) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=list(tool_calls), stop_reason="tool_use")


def _end(text: str = "done") -> LLMResponse:
    return LLMResponse(content=text, stop_reason="end_turn")


class MockSubAgent(CapabilityBase):
    """模拟一个已注册的子 Agent capability。"""

    def __init__(
        self,
        name: str,
        *,
        sleep_s: float = 0.0,
        result: Optional[Dict[str, Any]] = None,
        raise_exc: Optional[Exception] = None,
    ):
        super().__init__()
        self._name = name
        self._sleep = sleep_s
        self._result = result or {"response": f"{name} done"}
        self._raise = raise_exc
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"mock sub-agent {self._name}"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self._name, description=self.description)

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._raise is not None:
            raise self._raise
        return self._result


# =====================
# Fixtures
# =====================


@pytest.fixture
def task_registry(monkeypatch) -> TaskRegistry:
    """提供独立的 TaskRegistry 并打补丁让 dispatch_agent._get_task_registry 用它。"""
    registry = TaskRegistry()
    monkeypatch.setattr(
        "capabilities.tools.dispatch_agent._get_task_registry",
        lambda: registry,
    )
    return registry


@pytest.fixture
def cap_registry(monkeypatch) -> CapabilityRegistry:
    """提供独立的 CapabilityRegistry 并补丁 dispatch_agent._get_capability_registry。"""
    cr = CapabilityRegistry()
    monkeypatch.setattr(
        "capabilities.tools.dispatch_agent._get_capability_registry",
        lambda: cr,
    )
    return cr


@pytest.fixture
def dispatch_tool(cap_registry, task_registry):
    """构造 DispatchAgentCapability 实例并注册到 cap_registry。"""
    from capabilities.tools.dispatch_agent import DispatchAgentCapability

    tool = DispatchAgentCapability()
    cap_registry.register_native(tool)
    return tool


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """transcript 落盘隔离，避免 cross-test 污染。"""
    monkeypatch.setenv("AGENTIC_TASK_DATA_DIR", str(tmp_path / "tasks"))


# =====================
# 1. 立即返回 task_id
# =====================


async def test_dispatch_returns_task_id_immediately(
    cap_registry, task_registry, dispatch_tool
) -> None:
    """子 Agent 故意慢；dispatch_agent.execute 应立刻返回，不等子完成。"""
    slow_sub = MockSubAgent("slowcoder", sleep_s=0.5)
    cap_registry.register_native(slow_sub)

    started = time.monotonic()
    result = await dispatch_tool.execute(
        subagent_type="slowcoder", prompt="写排序算法"
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.1, f"dispatch should return fast, took {elapsed:.3f}s"
    assert result["status"] == "dispatched"
    assert result["task_id"]
    assert result["subagent_type"] == "slowcoder"

    # 等子任务完成后清理（避免 pytest 报 pending task warning）
    state = task_registry.get(result["task_id"])
    if state is not None:
        async_task = task_registry._asyncio_tasks.get(result["task_id"])
        if async_task is not None:
            await async_task


async def test_unknown_subagent_returns_error(
    cap_registry, task_registry, dispatch_tool
) -> None:
    result = await dispatch_tool.execute(
        subagent_type="bogus_agent", prompt="x"
    )
    assert "error" in result
    assert "unknown subagent_type" in result["error"]


async def test_missing_required_args(
    cap_registry, task_registry, dispatch_tool
) -> None:
    result = await dispatch_tool.execute(prompt="x")
    assert "error" in result and "subagent_type" in result["error"]
    result = await dispatch_tool.execute(subagent_type="x")
    assert "error" in result and "prompt" in result["error"]


# =====================
# 2. 嵌套保护
# =====================


async def test_max_depth_one_blocks_nested(
    cap_registry, task_registry, dispatch_tool
) -> None:
    sub = MockSubAgent("coder")
    cap_registry.register_native(sub)

    token = set_dispatch_depth(1)
    try:
        result = await dispatch_tool.execute(
            subagent_type="coder", prompt="x"
        )
    finally:
        reset_dispatch_depth(token)

    assert "error" in result
    assert "nested" in result["error"].lower()


def test_check_permissions_denies_at_max_depth(dispatch_tool) -> None:
    token = set_dispatch_depth(1)
    try:
        outcome = dispatch_tool.check_permissions(
            subagent_type="coder", prompt="x"
        )
    finally:
        reset_dispatch_depth(token)
    assert outcome["decision"] == "deny"
    assert "nested" in outcome["reason"].lower()


def test_check_permissions_allows_at_depth_zero(dispatch_tool) -> None:
    outcome = dispatch_tool.check_permissions(
        subagent_type="coder", prompt="x"
    )
    assert outcome["decision"] == "allow"


# =====================
# 3. 端到端：notification 回注父消息历史
# =====================


async def test_notification_appears_in_parent_messages(
    cap_registry, task_registry, dispatch_tool
) -> None:
    """父 Agent 第 1 轮调 dispatch_agent；第 2 轮 messages 应包含 <task-notification>。"""
    sub = MockSubAgent(
        "coder", result={"response": "已完成排序", "files": ["sort.py"]}
    )
    cap_registry.register_native(sub)

    parent_llm = ScriptedLLM(
        [
            _tool_use(
                [
                    ToolCall(
                        id="c1",
                        name="dispatch_agent",
                        arguments={"subagent_type": "coder", "prompt": "写排序"},
                    )
                ]
            ),
            _end("整体完成"),
        ]
    )
    parent = Agent(
        name="planner-test",
        llm_client=parent_llm,
        tools=[dispatch_tool],
    )

    # 设父 task_id 让 sub-task 能 attach parent_id
    parent_token = set_parent_task_id("parent-task-id-test")
    try:
        result = await parent.run({"message": "请规划任务"})
    finally:
        reset_parent_task_id(parent_token)

    # 第 2 轮 LLM 调用应该看到 <task-notification> user 消息
    assert len(parent_llm.calls) >= 2, "expected parent to make >=2 LLM calls"
    second_call = parent_llm.calls[1]
    notif_messages = [
        m for m in second_call
        if m.get("role") == "user" and "<task-notification>" in str(m.get("content", ""))
    ]
    assert notif_messages, "expected at least one <task-notification> user message in second LLM call"

    notif_content = notif_messages[-1]["content"]
    assert "<status>completed</status>" in notif_content
    assert "<subagent-type>coder</subagent-type>" in notif_content

    # 父 Agent 最终也正常返回
    assert result.get("response") == "整体完成"

    # 子任务在 registry 里
    sub_states = [t for t in task_registry.list() if t.parent_id == "parent-task-id-test"]
    assert len(sub_states) == 1
    assert sub_states[0].status == TaskStatus.COMPLETED


async def test_notification_failed_subagent(
    cap_registry, task_registry, dispatch_tool
) -> None:
    """子 Agent 抛异常时，notification status='failed' 且 messages 含 <error> 块。"""
    failing = MockSubAgent("crasher", raise_exc=RuntimeError("boom"))
    cap_registry.register_native(failing)

    parent_llm = ScriptedLLM(
        [
            _tool_use(
                [
                    ToolCall(
                        id="c1",
                        name="dispatch_agent",
                        arguments={"subagent_type": "crasher", "prompt": "x"},
                    )
                ]
            ),
            _end("ack"),
        ]
    )
    parent = Agent(
        name="parent",
        llm_client=parent_llm,
        tools=[dispatch_tool],
    )
    await parent.run({"message": "go"})

    second_call = parent_llm.calls[1]
    notif = next(
        (
            m
            for m in second_call
            if m.get("role") == "user"
            and "<task-notification>" in str(m.get("content", ""))
        ),
        None,
    )
    assert notif is not None
    assert "<status>failed</status>" in notif["content"]
    assert "boom" in notif["content"]
