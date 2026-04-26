"""OpenAI 客户端 — 支持 function calling (tool_use) + 流式传输"""
import json
import time
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
        generation_config: Optional[Dict[str, Any]] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.generation_config = generation_config or {}
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
        kwargs.update(self._request_options())

        # 转换工具定义为 OpenAI 格式
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        start = time.perf_counter()
        response = await self._create_with_compat_retry(kwargs)
        parsed = self._parse_response(response)
        parsed.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return parsed

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

    @classmethod
    def _parse_response(cls, response: Any) -> LLMResponse:
        """将 OpenAI 响应转为统一的 LLMResponse"""
        choice = response.choices[0]
        message = choice.message
        usage, raw_usage = cls._parse_usage(getattr(response, "usage", None))

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
                usage=usage,
                raw_usage=raw_usage,
            )

        return LLMResponse(
            content=message.content or "",
            stop_reason="end_turn",
            usage=usage,
            raw_usage=raw_usage,
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
        kwargs.update(self._request_options())
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        kwargs["stream_options"] = {"include_usage": True}
        start = time.perf_counter()
        try:
            stream = await self._create_with_compat_retry(kwargs)
        except Exception:
            # Some OpenAI-compatible gateways do not support stream_options.
            kwargs.pop("stream_options", None)
            stream = await self._create_with_compat_retry(kwargs)

        # 累积工具调用片段
        tool_call_buffers: Dict[int, Dict[str, Any]] = {}
        usage: Dict[str, int] = {}
        raw_usage: Optional[Dict[str, Any]] = None

        async for chunk in stream:
            chunk_usage, chunk_raw_usage = self._parse_usage(getattr(chunk, "usage", None))
            if chunk_usage:
                usage = chunk_usage
                raw_usage = chunk_raw_usage

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
        yield LLMStreamEvent(
            type="done",
            stop_reason=stop,
            usage=usage,
            raw_usage=raw_usage,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
        )

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

    def _request_options(self) -> Dict[str, Any]:
        """Return OpenAI Chat Completions parameters supported by this provider."""

        config = getattr(self, "generation_config", None) or {}
        openai_config = config.get("openai", {})
        if not isinstance(openai_config, dict):
            openai_config = {}

        options: Dict[str, Any] = {}

        for key in ("temperature", "top_p"):
            value = config.get(key)
            if value is not None:
                options[key] = value

        stop_sequences = config.get("stop_sequences")
        if isinstance(stop_sequences, list) and stop_sequences:
            options["stop"] = [str(item) for item in stop_sequences if str(item)]

        max_completion_tokens = openai_config.get("max_completion_tokens")
        if max_completion_tokens is None:
            max_completion_tokens = config.get("max_tokens")
        if max_completion_tokens:
            token_key = "max_tokens" if openai_config.get("use_legacy_max_tokens") else "max_completion_tokens"
            options[token_key] = int(max_completion_tokens)

        for key in ("presence_penalty", "frequency_penalty"):
            value = openai_config.get(key)
            if value is not None:
                options[key] = value

        reasoning_effort = str(openai_config.get("reasoning_effort") or "").strip()
        if reasoning_effort:
            options["reasoning_effort"] = reasoning_effort

        seed = openai_config.get("seed")
        if seed is not None:
            options["seed"] = int(seed)

        return options

    async def _create_with_compat_retry(self, kwargs: Dict[str, Any]) -> Any:
        """Create a completion, retrying legacy token names for compatible gateways."""

        try:
            return await self.client.chat.completions.create(**kwargs)
        except Exception:
            if "max_completion_tokens" not in kwargs or "max_tokens" in kwargs:
                raise
            fallback = dict(kwargs)
            fallback["max_tokens"] = fallback.pop("max_completion_tokens")
            return await self.client.chat.completions.create(**fallback)

    @staticmethod
    def _parse_usage(raw_usage: Any) -> tuple[Dict[str, int], Optional[Dict[str, Any]]]:
        if not raw_usage:
            return {}, None

        raw: Dict[str, Any]
        if isinstance(raw_usage, dict):
            raw = dict(raw_usage)
        else:
            dumped = raw_usage.model_dump() if hasattr(raw_usage, "model_dump") else None
            if isinstance(dumped, dict):
                raw = dumped
            else:
                raw = {
                    key: getattr(raw_usage, key)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if isinstance(getattr(raw_usage, key, None), (int, float))
                }

        if not raw:
            return {}, None

        input_tokens = raw.get("prompt_tokens")
        output_tokens = raw.get("completion_tokens")
        total_tokens = raw.get("total_tokens")

        usage = {}
        if input_tokens is not None:
            usage["input_tokens"] = int(input_tokens)
        if output_tokens is not None:
            usage["output_tokens"] = int(output_tokens)
        if total_tokens is not None:
            usage["total_tokens"] = int(total_tokens)
        elif usage:
            usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        return usage, raw
