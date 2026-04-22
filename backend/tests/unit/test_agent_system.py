"""Agent 系统单元测试

覆盖:
- Agent: 创建、run()、状态转换、元数据、capabilities
- AgentRegistry: 注册/注销、按名称/能力查找、list_all、批量 start/stop
- AgentLifecycleManager: start/stop、状态变更、健康检查、错误恢复
- AgentStatus 枚举
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

# 修复导入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from core.agent import (
    Agent,
    AgentRegistry,
    AgentLifecycleManager,
    AgentStatus,
    AgentMetadata,
)
from core.bus import SimpleBus, Event
from core.llm.base import BaseLLMClient, LLMResponse
from core.capability.base import CapabilityBase, CapabilitySchema


# =====================
# Mock LLM Client
# =====================


class MockLLMClient(BaseLLMClient):
    """测试用 LLM 客户端，返回固定响应"""

    def __init__(self, response: Optional[LLMResponse] = None):
        self._response = response or LLMResponse(content="test", stop_reason="end_turn")

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        return self._response


class FailingLLMClient(BaseLLMClient):
    """测试用 LLM 客户端，调用时抛出异常"""

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        raise RuntimeError("LLM call failed")


# =====================
# Mock Capability (Tool)
# =====================


class MockCapability(CapabilityBase):
    """测试用能力插件"""

    def __init__(self, cap_name: str, cap_description: str = "mock capability"):
        super().__init__()
        self._name = cap_name
        self._description = cap_description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self._name, description=self._description)

    async def execute(self, **kwargs: Any) -> Any:
        return {"result": "ok"}


# =====================
# Helper: 创建 Agent
# =====================


def make_agent(
    name: str,
    tools: Optional[List[CapabilityBase]] = None,
    llm_client: Optional[BaseLLMClient] = None,
    description: str = "",
) -> Agent:
    """创建一个带有 mock LLM 客户端的 Agent"""
    client = llm_client or MockLLMClient()
    return Agent(
        name=name,
        llm_client=client,
        tools=tools,
        description=description or f"Test agent: {name}",
    )


# =====================
# Fixtures
# =====================


@pytest.fixture
def bus():
    return SimpleBus()


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def coder_agent():
    return make_agent("coder", tools=[MockCapability("code_generation")])


@pytest.fixture
def reviewer_agent():
    return make_agent(
        "reviewer",
        tools=[MockCapability("code_review"), MockCapability("quality_analysis")],
    )


@pytest.fixture
def planner_agent():
    return make_agent(
        "planner",
        tools=[MockCapability("task_decomposition"), MockCapability("planning")],
    )


@pytest.fixture
def assistant_agent():
    return make_agent(
        "assistant",
        tools=[MockCapability("chat"), MockCapability("conversation")],
    )


# =====================
# AgentRegistry 测试
# =====================


class TestAgentRegistry:
    """AgentRegistry 测试"""

    def test_register_agent(self, registry, coder_agent):
        """注册 Agent"""
        registry.register(coder_agent)
        assert "coder" in registry
        assert len(registry) == 1

    def test_register_multiple(self, registry, coder_agent, reviewer_agent):
        """注册多个 Agent"""
        registry.register(coder_agent)
        registry.register(reviewer_agent)
        assert len(registry) == 2

    def test_register_overwrite(self, registry):
        """同名覆盖注册"""
        agent1 = make_agent("coder", tools=[MockCapability("old")])
        agent2 = make_agent("coder", tools=[MockCapability("new")])
        registry.register(agent1)
        registry.register(agent2)
        assert len(registry) == 1
        assert registry.get("coder").get_capabilities() == ["new"]

    def test_unregister(self, registry, coder_agent):
        """注销 Agent"""
        registry.register(coder_agent)
        registry.unregister("coder")
        assert "coder" not in registry
        assert len(registry) == 0

    def test_unregister_nonexistent(self, registry):
        """注销不存在的 Agent 不报错"""
        registry.unregister("nonexistent")
        assert len(registry) == 0

    def test_get_by_name(self, registry, coder_agent):
        """按名称获取"""
        registry.register(coder_agent)
        agent = registry.get("coder")
        assert agent is not None
        assert agent.name == "coder"

    def test_get_nonexistent(self, registry):
        """获取不存在的 Agent 返回 None"""
        assert registry.get("nonexistent") is None

    def test_find_by_capability(self, registry, coder_agent, reviewer_agent, planner_agent):
        """按能力查找"""
        registry.register(coder_agent)
        registry.register(reviewer_agent)
        registry.register(planner_agent)

        # 查找有 code_generation 能力的
        agents = registry.find_by_capability("code_generation")
        assert len(agents) == 1
        assert agents[0].name == "coder"

        # 查找有 planning 能力的
        agents = registry.find_by_capability("planning")
        assert len(agents) == 1
        assert agents[0].name == "planner"

    def test_find_by_capability_multiple(self, registry):
        """多个 Agent 有相同能力"""
        agent_a = make_agent("a", tools=[MockCapability("common"), MockCapability("unique_a")])
        agent_b = make_agent("b", tools=[MockCapability("common"), MockCapability("unique_b")])
        registry.register(agent_a)
        registry.register(agent_b)

        agents = registry.find_by_capability("common")
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"a", "b"}

    def test_find_by_capability_empty(self, registry, coder_agent):
        """查找不存在的能力返回空列表"""
        registry.register(coder_agent)
        agents = registry.find_by_capability("nonexistent")
        assert agents == []

    def test_list_all(self, registry, coder_agent, reviewer_agent):
        """列出所有 Agent 元数据"""
        registry.register(coder_agent)
        registry.register(reviewer_agent)

        all_meta = registry.list_all()
        assert len(all_meta) == 2
        assert all(isinstance(m, AgentMetadata) for m in all_meta)
        names = {m.name for m in all_meta}
        assert names == {"coder", "reviewer"}

    def test_list_all_empty(self, registry):
        """空注册表返回空列表"""
        assert registry.list_all() == []

    async def test_start_all(self, registry, coder_agent, reviewer_agent):
        """批量启动"""
        registry.register(coder_agent)
        registry.register(reviewer_agent)
        await registry.start_all()
        assert coder_agent.status == AgentStatus.IDLE
        assert reviewer_agent.status == AgentStatus.IDLE

    async def test_stop_all(self, registry, coder_agent, reviewer_agent):
        """批量停止"""
        registry.register(coder_agent)
        registry.register(reviewer_agent)
        await registry.start_all()
        await registry.stop_all()
        assert coder_agent.status == AgentStatus.STOPPED
        assert reviewer_agent.status == AgentStatus.STOPPED


# =====================
# Agent 状态与生命周期测试
# =====================


class TestAgentStatusAndLifecycle:
    """Agent 状态和生命周期测试"""

    def test_initial_status_is_idle(self, coder_agent):
        """新建 Agent 初始状态为 IDLE"""
        assert coder_agent.status == AgentStatus.IDLE

    async def test_start_sets_idle(self, coder_agent):
        """启动后状态为 IDLE"""
        coder_agent.status = AgentStatus.STOPPED
        await coder_agent.start()
        assert coder_agent.status == AgentStatus.IDLE

    async def test_stop_sets_stopped(self, coder_agent):
        """停止后状态变为 STOPPED"""
        await coder_agent.stop()
        assert coder_agent.status == AgentStatus.STOPPED

    async def test_run_sets_busy_then_idle(self):
        """run() 完成后回到 IDLE"""
        agent = make_agent("test")
        result = await agent.run({"message": "hello"})
        assert agent.status == AgentStatus.IDLE
        assert result == {"response": "test"}

    async def test_run_error_sets_error_status(self):
        """run() 出错时状态变为 ERROR"""
        agent = make_agent("fail", llm_client=FailingLLMClient())
        with pytest.raises(RuntimeError):
            await agent.run({"message": "hello"})
        assert agent.status == AgentStatus.ERROR

    def test_get_metadata(self, coder_agent):
        """获取元数据"""
        meta = coder_agent.get_metadata()
        assert isinstance(meta, AgentMetadata)
        assert meta.name == "coder"
        assert "code_generation" in meta.capabilities
        assert meta.status == AgentStatus.IDLE

    def test_get_capabilities(self, reviewer_agent):
        """获取能力列表"""
        caps = reviewer_agent.get_capabilities()
        assert "code_review" in caps
        assert "quality_analysis" in caps

    def test_get_capabilities_empty(self):
        """没有工具的 Agent 返回空能力列表"""
        agent = make_agent("empty")
        assert agent.get_capabilities() == []

    async def test_run_text_output(self):
        """text 模式 run() 返回 {response: ...}"""
        llm = MockLLMClient(LLMResponse(content="hello world", stop_reason="end_turn"))
        agent = Agent(name="t", llm_client=llm, output_format="text")
        result = await agent.run({"msg": "hi"})
        assert result == {"response": "hello world"}

    async def test_run_json_output(self):
        """json 模式 run() 解析 JSON 输出"""
        llm = MockLLMClient(
            LLMResponse(content='{"key": "value"}', stop_reason="end_turn")
        )
        agent = Agent(name="j", llm_client=llm, output_format="json")
        result = await agent.run({"msg": "hi"})
        assert result == {"key": "value"}


# =====================
# AgentLifecycleManager 测试
# =====================


class TestAgentLifecycleManager:
    """AgentLifecycleManager 测试"""

    @pytest.fixture
    def setup(self, bus, registry, coder_agent, reviewer_agent):
        registry.register(coder_agent)
        registry.register(reviewer_agent)
        lcm = AgentLifecycleManager(registry, bus)
        return lcm, coder_agent, reviewer_agent

    async def test_start_agent(self, setup):
        """启动单个 Agent"""
        lcm, coder, _ = setup
        result = await lcm.start_agent("coder")
        assert result is True
        assert coder.status == AgentStatus.IDLE

    async def test_start_nonexistent_agent(self, setup):
        """启动不存在的 Agent 返回 False"""
        lcm, _, _ = setup
        result = await lcm.start_agent("nonexistent")
        assert result is False

    async def test_stop_agent(self, setup):
        """停止单个 Agent"""
        lcm, coder, _ = setup
        await lcm.start_agent("coder")
        result = await lcm.stop_agent("coder")
        assert result is True
        assert coder.status == AgentStatus.STOPPED

    async def test_stop_nonexistent_agent(self, setup):
        """停止不存在的 Agent 返回 False"""
        lcm, _, _ = setup
        result = await lcm.stop_agent("nonexistent")
        assert result is False

    async def test_restart_agent(self, setup):
        """重启 Agent"""
        lcm, coder, _ = setup
        await lcm.start_agent("coder")
        result = await lcm.restart_agent("coder")
        assert result is True
        assert coder.status == AgentStatus.IDLE

    async def test_health_check(self, setup):
        """健康检查"""
        lcm, coder, reviewer = setup
        await lcm.start_agent("coder")
        # reviewer 未通过 lcm 启动，但 Agent 新建默认 IDLE
        health = await lcm.health_check()
        assert health["coder"] == AgentStatus.IDLE
        assert health["reviewer"] == AgentStatus.IDLE

    async def test_check_and_recover(self, registry, bus):
        """错误恢复"""
        agent = make_agent("test")
        registry.register(agent)
        lcm = AgentLifecycleManager(registry, bus)

        # 手动设置 ERROR 状态
        await lcm.start_agent("test")
        agent.status = AgentStatus.ERROR

        # check_and_recover 应该尝试重启
        await lcm.check_and_recover()
        assert agent.status == AgentStatus.IDLE

    async def test_max_restarts_limit(self, registry, bus):
        """超过最大重启次数后不再重启"""
        agent = make_agent("test")
        registry.register(agent)
        lcm = AgentLifecycleManager(registry, bus, max_restarts=2)

        await lcm.start_agent("test")

        # 模拟多次失败
        for _ in range(3):
            agent.status = AgentStatus.ERROR
            await lcm.check_and_recover()

        # 第 3 次时已经超过限制，不应再恢复
        agent.status = AgentStatus.ERROR
        await lcm.check_and_recover()
        # 由于已用完重启次数，agent 应该保持 ERROR
        assert agent.status == AgentStatus.ERROR
