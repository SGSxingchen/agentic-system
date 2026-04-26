"""Phase A 单元测试 — Agent 反应式工具循环底盘加固

覆盖:
- 并发分组：is_concurrency_safe=True 的工具应同时执行
- 串行分组：is_concurrency_safe=False 的工具应顺序执行
- Result Budget：超 max_result_size 的工具输出被截断且打 truncated 标记
- 权限闸门：check_permissions 返回 deny 时不调用 execute，错误回写到 LLM 上下文
- Token 预算硬终止：累计输入+输出超 budget 时直接终止 + 返回 error
- Token 预算 nudge：跨过 nudge_threshold 后下一轮 LLM 看到 system 提醒
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 修复导入路径（与同目录其他测试一致）
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.agent import Agent
from core.capability.base import CapabilityBase, CapabilitySchema
from core.llm.base import BaseLLMClient, LLMResponse, ToolCall


# =====================
# Mock LLM
# =====================


class ScriptedLLM(BaseLLMClient):
    """按预设序列返回 LLMResponse；记录每次 chat 的 messages 副本。"""

    def __init__(self, responses: List[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: List[List[Dict[str, Any]]] = []

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        if not self._responses:
            return LLMResponse(content="(script exhausted)", stop_reason="end_turn")
        return self._responses.pop(0)


def _tool_use(
    tool_calls: List[ToolCall],
    usage: Optional[Dict[str, int]] = None,
) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=list(tool_calls),
        stop_reason="tool_use",
        usage=usage or {},
    )


def _end(text: str = "done", usage: Optional[Dict[str, int]] = None) -> LLMResponse:
    return LLMResponse(content=text, stop_reason="end_turn", usage=usage or {})


# =====================
# Mock Tools
# =====================


class TimedTool(CapabilityBase):
    """带可控延迟的工具，记录调用次数与时序。"""

    def __init__(
        self,
        name: str,
        *,
        sleep_s: float = 0.0,
        concurrency_safe: bool = True,
        max_result_size: int = 1000,
    ) -> None:
        super().__init__()
        self._name = name
        self._sleep = sleep_s
        self._concurrent = concurrency_safe
        self._max_size = max_result_size
        self.call_count = 0
        self.start_times: List[float] = []
        self.finish_times: List[float] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "timed mock"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self._name,
            description=self.description,
            is_read_only=True,
            is_concurrency_safe=self._concurrent,
            max_result_size=self._max_size,
        )

    async def execute(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.start_times.append(time.monotonic())
        if self._sleep:
            await asyncio.sleep(self._sleep)
        self.finish_times.append(time.monotonic())
        return {"name": self._name, "ok": True}


class BigOutputTool(CapabilityBase):
    """返回超大字符串，用于验证 max_result_size 截断。"""

    @property
    def name(self) -> str:
        return "big"

    @property
    def description(self) -> str:
        return "produces oversized output"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=200,
        )

    async def execute(self, **kwargs: Any) -> Any:
        return "x" * 5000


class GuardedTool(CapabilityBase):
    """check_permissions 永远拒绝，execute 不应被调用。"""

    def __init__(self) -> None:
        super().__init__()
        self.execute_calls = 0

    @property
    def name(self) -> str:
        return "guarded"

    @property
    def description(self) -> str:
        return "always denies"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            is_concurrency_safe=False,
            max_result_size=500,
        )

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        return {"decision": "deny", "reason": "always denied for tests"}

    async def execute(self, **kwargs: Any) -> Any:
        self.execute_calls += 1
        return {"unreachable": True}


# =====================
# 1. 并发 / 串行调度
# =====================


async def test_concurrent_dispatch_runs_in_parallel() -> None:
    """两个 concurrency_safe 的工具应并发执行；总耗时接近单个工具时延。"""
    tool_a = TimedTool("a", sleep_s=0.2, concurrency_safe=True)
    tool_b = TimedTool("b", sleep_s=0.2, concurrency_safe=True)

    llm = ScriptedLLM([
        _tool_use([
            ToolCall(id="ca", name="a", arguments={}),
            ToolCall(id="cb", name="b", arguments={}),
        ]),
        _end("after"),
    ])
    agent = Agent(name="t1", llm_client=llm, tools=[tool_a, tool_b])

    started = time.monotonic()
    result = await agent.run({"message": "go"})
    elapsed = time.monotonic() - started

    assert tool_a.call_count == 1
    assert tool_b.call_count == 1
    # 两个 0.2s 工具并发 → dispatch 总耗时应远小于 0.4s
    assert elapsed < 0.35, f"expected concurrent (<0.35s), got {elapsed:.3f}s"
    assert result.get("response") == "after"


async def test_process_compatibility_delegates_to_run() -> None:
    """旧编排入口 process() 应能调用当前通用 Agent。"""
    llm = ScriptedLLM([_end("compat")])
    agent = Agent(name="compat", llm_client=llm)

    result = await agent.process({"message": "go"})

    assert result == {"response": "compat"}


async def test_serial_dispatch_for_unsafe_tools() -> None:
    """concurrency_safe=False 的工具应顺序执行，调用区间不重叠。"""
    tool_a = TimedTool("a", sleep_s=0.05, concurrency_safe=False)
    tool_b = TimedTool("b", sleep_s=0.05, concurrency_safe=False)

    llm = ScriptedLLM([
        _tool_use([
            ToolCall(id="ca", name="a", arguments={}),
            ToolCall(id="cb", name="b", arguments={}),
        ]),
        _end("ok"),
    ])
    agent = Agent(name="t2", llm_client=llm, tools=[tool_a, tool_b])
    await agent.run({"message": "go"})

    # b 必须在 a 完成之后才开始（允许微小调度抖动）
    assert tool_b.start_times[0] >= tool_a.finish_times[0] - 1e-3


# =====================
# 2. Result Budget 截断
# =====================


async def test_result_truncation_marks_truncated_payload() -> None:
    big = BigOutputTool()
    llm = ScriptedLLM([
        _tool_use([ToolCall(id="cb", name="big", arguments={})]),
        _end("done"),
    ])
    agent = Agent(name="t3", llm_client=llm, tools=[big])
    await agent.run({"message": "go"})

    # 第 2 次 LLM 调用看到的就是截断后的 tool 消息
    second_call_messages = llm.calls[1]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert tool_msgs, "expected at least one tool message"
    payload = json.loads(tool_msgs[-1]["content"])
    assert payload.get("truncated") is True
    assert "[truncated" in payload.get("content", "")
    assert payload.get("max_size") == 200


# =====================
# 3. 权限 deny
# =====================


async def test_permission_deny_skips_execute() -> None:
    guarded = GuardedTool()
    llm = ScriptedLLM([
        _tool_use([ToolCall(id="cg", name="guarded", arguments={"x": 1})]),
        _end("ok"),
    ])
    agent = Agent(name="t4", llm_client=llm, tools=[guarded])
    await agent.run({"message": "go"})

    assert guarded.execute_calls == 0
    second_call_messages = llm.calls[1]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert tool_msgs
    payload = json.loads(tool_msgs[-1]["content"])
    assert payload.get("permission_denied") is True
    assert "Permission denied" in payload.get("error", "")


# =====================
# 4. Token 预算 — 硬终止
# =====================


async def test_token_budget_hard_stop_returns_error() -> None:
    tool = TimedTool("a", sleep_s=0.0, concurrency_safe=True)
    llm = ScriptedLLM([
        _tool_use(
            [ToolCall(id="c1", name="a", arguments={})],
            usage={"input_tokens": 60_000, "output_tokens": 0},
        ),
        _tool_use(
            [ToolCall(id="c2", name="a", arguments={})],
            usage={"input_tokens": 50_000, "output_tokens": 0},
        ),
        _end("never reached"),
    ])
    agent = Agent(
        name="t5",
        llm_client=llm,
        tools=[tool],
        max_iterations=10,
        token_budget=100_000,
    )
    result = await agent.run({"message": "go"})

    assert result.get("error") == "token_budget_exceeded"
    assert (result.get("used") or 0) >= 100_000
    assert result.get("budget") == 100_000
    # 不应再调用第三次 LLM（budget gate 在第 2 轮 dispatch 后触发）
    assert len(llm.calls) == 2


# =====================
# 5. Token 预算 — nudge
# =====================


async def test_token_budget_nudge_inserts_system_message() -> None:
    tool = TimedTool("a", sleep_s=0.0, concurrency_safe=True)
    llm = ScriptedLLM([
        _tool_use(
            [ToolCall(id="c1", name="a", arguments={})],
            usage={"input_tokens": 30_000},
        ),
        _tool_use(
            [ToolCall(id="c2", name="a", arguments={})],
            usage={"input_tokens": 60_000},
        ),
        _end("done", usage={"input_tokens": 5_000}),
    ])
    agent = Agent(
        name="t6",
        llm_client=llm,
        tools=[tool],
        max_iterations=10,
        token_budget=100_000,
        token_budget_nudge_threshold=0.85,
    )
    result = await agent.run({"message": "go"})

    # 第 3 次 LLM 调用应已包含 nudge system 消息
    assert len(llm.calls) == 3
    third = llm.calls[2]
    nudges = [
        m
        for m in third
        if m.get("role") == "system" and "已用" in str(m.get("content", ""))
    ]
    assert nudges, "expected a budget nudge system message before the 3rd LLM call"
    assert result.get("response") == "done"
