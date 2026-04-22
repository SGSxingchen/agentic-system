"""Anthropic 客户端 — 支持 tool_use + 流式传输"""
import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import BaseLLMClient, LLMResponse, LLMStreamEvent, ToolCall


class AnthropicClient(BaseLLMClient):
    """Anthropic (Claude) 客户端"""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        try:
            from anthropic import AsyncAnthropic

            kwargs: Dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self.client = AsyncAnthropic(**kwargs)
        except ImportError:
            raise ImportError("请安装 anthropic: pip install anthropic")

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        """发送聊天消息，支持 tool_use"""
        # 分离 system 消息
        system_msg = ""
        api_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            elif msg["role"] == "tool":
                # Anthropic 格式: tool_result content block
                api_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                # 将 tool_calls 转回 Anthropic 的 tool_use content block
                content_blocks = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    if isinstance(tc, ToolCall):
                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.arguments,
                            }
                        )
                    elif isinstance(tc, dict):
                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc.get("id", ""),
                                "name": tc.get("name", ""),
                                "input": tc.get("arguments", {}),
                            }
                        )
                api_messages.append({"role": "assistant", "content": content_blocks})
            else:
                api_messages.append(msg)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": api_messages,
        }

        if system_msg:
            kwargs["system"] = system_msg

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self.client.messages.create(**kwargs)
        return self._parse_response(response)

    @staticmethod
    def _convert_tools(schemas: List[Any]) -> List[Dict[str, Any]]:
        """将 CapabilitySchema 列表转为 Anthropic tool 格式

        Anthropic 格式:
        {
            "name": "...",
            "description": "...",
            "input_schema": { JSON Schema }
        }
        """
        tools = []
        for schema in schemas:
            tool = {
                "name": schema.name,
                "description": schema.description or "",
                "input_schema": schema.parameters
                if schema.parameters
                else {"type": "object", "properties": {}},
            }
            tools.append(tool)
        return tools

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """将 Anthropic 响应转为统一的 LLMResponse"""
        content_text = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        if tool_calls:
            return LLMResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                stop_reason="tool_use",
            )

        return LLMResponse(
            content=content_text,
            stop_reason="end_turn",
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """流式聊天 — 逐步 yield 文本片段和工具调用

        使用 create(stream=True) 以兼容第三方代理。
        """
        # 复用消息转换逻辑
        system_msg = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            elif msg["role"] == "tool":
                api_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": msg.get("tool_call_id", ""), "content": msg.get("content", "")}],
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                content_blocks = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    if isinstance(tc, ToolCall):
                        content_blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                    elif isinstance(tc, dict):
                        content_blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": tc.get("name", ""), "input": tc.get("arguments", {})})
                api_messages.append({"role": "assistant", "content": content_blocks})
            else:
                api_messages.append(msg)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": api_messages,
            "stream": True,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        current_tool_id = ""
        current_tool_name = ""
        current_tool_input = ""
        stop_reason = "end_turn"

        try:
            stream = await self.client.messages.create(**kwargs)
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type") and block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_name = block.name
                        current_tool_input = ""

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text"):
                        yield LLMStreamEvent(type="text", content=delta.text)
                    elif hasattr(delta, "partial_json"):
                        current_tool_input += delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_name:
                        try:
                            arguments = json.loads(current_tool_input) if current_tool_input else {}
                        except json.JSONDecodeError:
                            arguments = {"raw": current_tool_input}
                        yield LLMStreamEvent(
                            type="tool_use",
                            tool_call=ToolCall(id=current_tool_id, name=current_tool_name, arguments=arguments),
                        )
                        current_tool_name = ""
                        current_tool_input = ""

                elif event.type == "message_delta":
                    if hasattr(event, "delta") and hasattr(event.delta, "stop_reason"):
                        stop_reason = event.delta.stop_reason or "end_turn"

        except Exception as e:
            # 流式不可用时回退到非流式
            import logging
            logging.getLogger(__name__).warning("Streaming failed, falling back: %s", e)
            response = await self.client.messages.create(
                **{k: v for k, v in kwargs.items() if k != "stream"}
            )
            parsed = self._parse_response(response)
            if parsed.content:
                yield LLMStreamEvent(type="text", content=parsed.content)
            for tc in parsed.tool_calls:
                yield LLMStreamEvent(type="tool_use", tool_call=tc)
            stop_reason = parsed.stop_reason

        yield LLMStreamEvent(type="done", stop_reason=stop_reason)
