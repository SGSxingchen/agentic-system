"""AgentCapability — 将 Agent 包装为 CapabilityBase

使 Agent 可以注册到 CapabilityRegistry，被 Pipeline 和其他 Agent 通过
统一的 capability 接口调用。当 Agent 被其他 Agent 当工具调用时，
LLM 通过 get_schema() 返回的 input_schema 了解该传什么参数。
"""
from typing import Any, AsyncIterator, Dict, Optional

from .base import CapabilityBase, CapabilitySchema
from ..agent.agent import Agent


class AgentCapability(CapabilityBase):
    """将 Agent 适配为 CapabilityBase 接口

    Pipeline 不需要知道 step 调用的是 Agent 还是工具，
    统一通过 CapabilityRegistry.execute() 调用。

    Args:
        agent: 被包装的 Agent 实例
        input_schema: 可选的 JSON Schema，描述该 Agent 接受的参数。
                      来自 agents.yaml 中的 input_schema 字段。
                      如果不提供，使用通用的 message 参数。
    """

    def __init__(
        self,
        agent: Agent,
        input_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._input_schema = input_schema or {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "发送给该智能体的请求内容",
                },
            },
            "required": ["message"],
        }

    @property
    def name(self) -> str:
        return self._agent.name

    @property
    def description(self) -> str:
        return self._agent._description

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters=self._input_schema,
            returns="Agent processing result dict",
        )

    async def execute(self, **kwargs: Any) -> Any:
        """调用 Agent 的 run() 方法"""
        return await self._agent.run(kwargs)

    async def execute_stream(self, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
        """流式调用 Agent 的 run_stream() 方法"""
        async for event in self._agent.run_stream(kwargs):
            yield event

    def validate_input(self, **kwargs: Any) -> bool:
        """Agent 接受任意 dict 输入"""
        return True
