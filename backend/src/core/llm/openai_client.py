"""OpenAI 客户端 — 支持 function calling (tool_use) + 流式传输"""
import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import BaseLLMClient, LLMResponse, LLMStreamEvent, ToolCall


class OpenAIClient(BaseLLMClient):
    """OpenAI 兼容客户端（支持 OpenAI / DeepSeek / 其他兼容 API）"""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        try:
            from openai import AsyncOpenAI

            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self.client = AsyncOpenAI(**kwargs)
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        """发送聊天消息，支持 function calling"""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
        }

        # 转换工具定义为 OpenAI 格式
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self.client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    @staticmethod
    def _convert_tools(schemas: List[Any]) -> List[Dict[str, Any]]:
        """将 CapabilitySchema 列表转为 OpenAI function calling 格式

        OpenAI 格式:
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { JSON Schema }
            }
        }
        """
        tools = []
        for schema in schemas:
            tool = {
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description or "",
                    "parameters": schema.parameters
                    if schema.parameters
                    else {"type": "object", "properties": {}},
                },
            }
            tools.append(tool)
        return tools

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """将 OpenAI 响应转为统一的 LLMResponse"""
        choice = response.choices[0]
        message = choice.message

        # 检查是否有 tool_calls
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {"raw": tc.function.arguments}

                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
                    )
                )
            return LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
                stop_reason="tool_use",
            )

        return LLMResponse(
            content=message.content or "",
            stop_reason="end_turn",
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """流式聊天 — 逐步 yield 文本片段和工具调用"""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        stream = await self.client.chat.completions.create(**kwargs)

        # 累积工具调用片段
        tool_call_buffers: Dict[int, Dict[str, Any]] = {}

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # 文本片段
            if delta.content:
                yield LLMStreamEvent(type="text", content=delta.content)

            # 工具调用片段（OpenAI 分多个 chunk 发送）
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_buffers:
                        tool_call_buffers[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name or "" if tc_delta.function else "",
                            "arguments": "",
                        }
                    buf = tool_call_buffers[idx]
                    if tc_delta.id:
                        buf["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            buf["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            buf["arguments"] += tc_delta.function.arguments

            # chunk 结束标记
            finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
            if finish_reason:
                break

        # 流结束后，输出完整的工具调用
        for buf in tool_call_buffers.values():
            try:
                arguments = json.loads(buf["arguments"])
            except (json.JSONDecodeError, TypeError):
                arguments = {"raw": buf["arguments"]}
            yield LLMStreamEvent(
                type="tool_use",
                tool_call=ToolCall(
                    id=buf["id"] or str(uuid.uuid4()),
                    name=buf["name"],
                    arguments=arguments,
                ),
            )

        stop = "tool_use" if tool_call_buffers else "end_turn"
        yield LLMStreamEvent(type="done", stop_reason=stop)

    @classmethod
    def _convert_messages(cls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将中立消息格式转换为 OpenAI Chat Completions 可接受的格式。"""
        converted: List[Dict[str, Any]] = []
        for message in messages:
            normalized = dict(message)
            tool_calls = normalized.get("tool_calls")
            if normalized.get("role") == "assistant" and tool_calls:
                normalized["tool_calls"] = [
                    cls._convert_tool_call_message(tc) for tc in tool_calls
                ]
            converted.append(normalized)
        return converted

    @staticmethod
    def _convert_tool_call_message(tool_call: Any) -> Dict[str, Any]:
        """将 ToolCall 或中立 dict 转为 OpenAI tool_calls 消息结构。"""
        if isinstance(tool_call, ToolCall):
            tool_id = tool_call.id
            name = tool_call.name
            arguments = tool_call.arguments
        elif isinstance(tool_call, dict):
            if tool_call.get("type") == "function" and "function" in tool_call:
                return tool_call
            tool_id = tool_call.get("id", "")
            function = tool_call.get("function", {})
            name = tool_call.get("name") or function.get("name", "")
            arguments = tool_call.get("arguments", function.get("arguments", {}))
        else:
            raise TypeError(f"Unsupported tool call type: {type(tool_call)!r}")

        if isinstance(arguments, str):
            argument_text = arguments
        else:
            try:
                argument_text = json.dumps(arguments or {}, ensure_ascii=False)
            except (TypeError, ValueError):
                argument_text = json.dumps({"raw": str(arguments)}, ensure_ascii=False)

        return {
            "id": tool_id or str(uuid.uuid4()),
            "type": "function",
            "function": {
                "name": name,
                "arguments": argument_text,
            },
        }
