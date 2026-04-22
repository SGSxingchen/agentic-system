"""LLM 客户端基类与通用类型

定义所有 LLM 客户端共享的抽象接口和数据类型。
CapabilitySchema 格式的 tools 由各客户端自行转换为对应 API 格式。
"""
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class ToolCall:
    """LLM 请求的工具调用（中立格式，屏蔽 OpenAI/Anthropic 差异）"""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """LLM 响应（统一格式）

    Attributes:
        content: 文本响应（stop_reason="end_turn" 时有值）
        tool_calls: LLM 请求的工具调用列表（stop_reason="tool_use" 时有值）
        stop_reason: 停止原因 — "end_turn" 表示正常结束，"tool_use" 表示需要执行工具
    """

    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"


@dataclass
class LLMStreamEvent:
    """流式响应事件（逐步产出）

    Attributes:
        type: 事件类型 — "text" 文本片段, "tool_use" 完整工具调用, "done" 流结束
        content: 文本内容（type="text" 时）
        tool_call: 工具调用（type="tool_use" 时）
        stop_reason: 停止原因（type="done" 时）
    """

    type: str  # "text" | "tool_use" | "done"
    content: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    stop_reason: Optional[str] = None


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类

    子类需实现 chat() 方法，支持可选的 tools 参数。
    tools 参数接收 CapabilitySchema 列表（中立格式），
    各子类在内部转换为对应 API 的 tool 格式。
    """

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        """发送聊天消息，可选传入工具定义"""
        pass

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """流式聊天 — 逐步 yield LLMStreamEvent

        默认实现: 回退到非流式 chat()，一次性 yield 完整结果。
        子类可覆盖以实现真正的流式传输。
        """
        response = await self.chat(messages, tools)
        if response.content:
            yield LLMStreamEvent(type="text", content=response.content)
        for tc in response.tool_calls:
            yield LLMStreamEvent(type="tool_use", tool_call=tc)
        yield LLMStreamEvent(
            type="done",
            stop_reason=response.stop_reason,
        )
