"""Agent 注册表 - 管理 Agent 的注册、发现和批量生命周期"""
from typing import Dict, List, Optional

from .agent import Agent, AgentMetadata


class AgentRegistry:
    """Agent 注册表

    职责:
    - 注册 / 注销 Agent
    - 按名称获取
    - 按能力查找
    - 列出所有 Agent 元数据
    - 批量启动 / 停止
    """

    def __init__(self) -> None:
        self._agents: Dict[str, Agent] = {}

    # ─── 注册与注销 ─────────────────────────────────────

    def register(self, agent: Agent) -> None:
        """注册 Agent（同名覆盖）"""
        self._agents[agent.name] = agent

    def unregister(self, name: str) -> None:
        """注销 Agent，不存在时忽略"""
        self._agents.pop(name, None)

    # ─── 查询 ─────────────────────────────────────────────

    def get(self, name: str) -> Optional[Agent]:
        """按名称获取 Agent"""
        return self._agents.get(name)

    def find_by_capability(self, capability: str) -> List[Agent]:
        """按能力查找所有拥有该能力的 Agent"""
        return [
            agent
            for agent in self._agents.values()
            if capability in agent.get_capabilities()
        ]

    def list_all(self) -> List[AgentMetadata]:
        """列出所有已注册 Agent 的元数据"""
        return [agent.get_metadata() for agent in self._agents.values()]

    # ─── 批量生命周期 ────────────────────────────────────

    async def start_all(self) -> None:
        """启动所有已注册 Agent"""
        for agent in self._agents.values():
            await agent.start()

    async def stop_all(self) -> None:
        """停止所有已注册 Agent"""
        for agent in self._agents.values():
            await agent.stop()

    # ─── 辅助 ─────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents
