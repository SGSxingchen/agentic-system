"""通用配置化 Agent — 行为完全由 YAML 定义

核心特性:
- 所有行为（system_prompt, tools, output_format）由配置驱动
- 内置 tool_use 循环：LLM 自主决定调用哪些工具
- 支持流式传输：run_stream() 逐步 yield 中间事件
- 新增 Agent 只需在 agents.yaml 加一条记录，零代码
"""
import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ..llm.base import BaseLLMClient, LLMResponse, LLMStreamEvent, ToolCall
from ..capability.base import CapabilityBase
from ..task.context import (
    set_notification_box,
    reset_notification_box,
)
from ..task.notifications import make_user_message
from ..prompts import build_token_budget_nudge, format_untrusted_memory_context
from ..persona import build_persona_prompt_block, get_effective_persona

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent 状态枚举"""

    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentMetadata:
    """Agent 元数据"""

    name: str
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.STOPPED


class Agent:
    """通用配置化 Agent

    不需要继承或写子类。Agent 的行为完全由构造参数决定：
    - system_prompt: 定义 Agent 的角色和行为
    - tools: Agent 可调用的工具列表（CapabilityBase 实例）
    - output_format: LLM 最终输出的解析方式（"text" 或 "json"）

    内部实现 tool_use 循环：
    1. 构建 system_prompt + user_message
    2. 调用 LLM（带 tool 定义）
    3. 如果 LLM 请求工具调用 → 执行工具 → 将结果反馈 → 回到 2
    4. 如果 LLM 返回文本 → 解析输出 → 返回结果
    """

    def __init__(
        self,
        name: str,
        llm_client: BaseLLMClient,
        system_prompt: str = "",
        tools: Optional[List[CapabilityBase]] = None,
        output_format: str = "text",
        max_iterations: int = 10,
        description: str = "",
        token_budget: Optional[int] = None,
        token_budget_nudge_threshold: float = 0.85,
        runtime_config: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.llm = llm_client
        self.system_prompt = system_prompt
        self._tools = tools or []
        self._output_format = output_format
        self._max_iterations = max_iterations
        self._description = description
        self._token_budget = token_budget if (token_budget and token_budget > 0) else None
        self._token_budget_nudge_threshold = max(0.0, min(1.0, token_budget_nudge_threshold))
        self._runtime_config = runtime_config or {}
        self._status = AgentStatus.IDLE

    # ─── 主循环 ─────────────────────────────────────────────

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Agent 主循环: prompt → LLM → tool_use → 循环 → 最终结果

        Args:
            input_data: 输入数据字典

        Returns:
            处理结果字典
        """
        self._status = AgentStatus.BUSY
        notification_box: List[Dict[str, Any]] = []
        box_token = set_notification_box(notification_box)
        try:
            messages = self._build_messages(input_data)
            tool_schemas = [t.get_schema() for t in self._tools]
            total_usage: Dict[str, int] = {}
            total_elapsed_ms = 0.0
            nudged = False

            for iteration in range(self._max_iterations):
                await self._drain_notifications(notification_box, messages)
                response = await self.llm.chat(
                    messages,
                    tools=tool_schemas if tool_schemas else None,
                )
                total_usage = self._merge_usage(total_usage, response.usage)
                if response.elapsed_ms:
                    total_elapsed_ms += response.elapsed_ms

                # LLM 返回最终文本 → 结束循环
                if response.stop_reason != "tool_use":
                    self._status = AgentStatus.IDLE
                    result = self._parse_output(response.content or "")
                    return self._attach_metrics(result, total_usage, total_elapsed_ms)

                # LLM 请求工具调用 → 按元数据分组并发/串行执行 → 继续循环
                # 先添加 assistant 消息（含 tool_calls）
                assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": response.tool_calls}
                if response.content:
                    assistant_msg["content"] = response.content
                messages.append(assistant_msg)

                dispatched = await self._dispatch_tool_calls(response.tool_calls)
                for tc, result in dispatched:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": self._serialize_tool_result(result),
                        }
                    )

                logger.debug(
                    "Agent '%s' iteration %d: executed %d tool calls",
                    self.name,
                    iteration + 1,
                    len(response.tool_calls),
                )

                action, nudge_msg, nudged = self._token_budget_check(total_usage, nudged)
                if action == "stop":
                    self._status = AgentStatus.ERROR
                    return self._attach_metrics(
                        {
                            "error": "token_budget_exceeded",
                            "used": self._used_tokens(total_usage),
                            "budget": self._token_budget,
                        },
                        total_usage,
                        total_elapsed_ms,
                    )
                if nudge_msg:
                    messages.append({"role": "system", "content": nudge_msg})

            # 达到最大迭代次数
            self._status = AgentStatus.ERROR
            logger.warning(
                "Agent '%s' reached max iterations (%d)",
                self.name,
                self._max_iterations,
            )
            result = {"error": f"Agent '{self.name}' reached max iterations ({self._max_iterations})"}
            return self._attach_metrics(result, total_usage, total_elapsed_ms)

        except Exception as exc:
            self._status = AgentStatus.ERROR
            logger.error("Agent '%s' failed: %s", self.name, exc)
            raise
        finally:
            reset_notification_box(box_token)

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible one-shot entrypoint used by legacy orchestrators."""

        return await self.run(input_data)

    # ─── 流式主循环 ─────────────────────────────────────────

    async def run_stream(self, input_data: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """流式 Agent 主循环: 逐步 yield 事件

        事件类型:
        - {"type": "thinking", "content": "..."} — LLM 文本片段
        - {"type": "tool_call", "tool": "...", "args": {...}} — 开始调用工具
        - {"type": "tool_result", "tool": "...", "result": {...}} — 工具返回
        - {"type": "done", "content": "..."} — 最终结果
        """
        self._status = AgentStatus.BUSY
        notification_box: List[Dict[str, Any]] = []
        box_token = set_notification_box(notification_box)
        try:
            messages = self._build_messages(input_data)
            tool_schemas = [t.get_schema() for t in self._tools]
            total_usage: Dict[str, int] = {}
            total_elapsed_ms = 0.0
            nudged = False

            for iteration in range(self._max_iterations):
                await self._drain_notifications(notification_box, messages)

                # 收集本轮流式输出
                full_text = ""
                tool_calls: List[ToolCall] = []
                stop_reason = "end_turn"

                async for event in self.llm.chat_stream(
                    messages,
                    tools=tool_schemas if tool_schemas else None,
                ):
                    if event.type == "text" and event.content:
                        full_text += event.content
                        yield {"type": "thinking", "content": event.content}
                    elif event.type == "tool_use" and event.tool_call:
                        tool_calls.append(event.tool_call)
                    elif event.type == "done":
                        stop_reason = event.stop_reason or "end_turn"
                        total_usage = self._merge_usage(total_usage, event.usage)
                        if event.elapsed_ms:
                            total_elapsed_ms += event.elapsed_ms

                # LLM 返回最终文本 → 结束
                if stop_reason != "tool_use":
                    self._status = AgentStatus.IDLE
                    result = self._parse_output(full_text)
                    yield {
                        "type": "done",
                        "content": result,
                        "usage": total_usage,
                        "elapsed_ms": round(total_elapsed_ms, 2) if total_elapsed_ms else None,
                    }
                    return

                # 工具调用：先按 LLM 原顺序逐个 yield tool_call，再并发/串行分组执行
                assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
                if full_text:
                    assistant_msg["content"] = full_text
                messages.append(assistant_msg)

                for tc in tool_calls:
                    yield {
                        "type": "tool_call",
                        "tool": tc.name,
                        "tool_call_id": tc.id,
                        "args": tc.arguments,
                        "concurrent": self._is_concurrent_safe(tc),
                    }

                dispatched = await self._dispatch_tool_calls(tool_calls)
                for tc, result in dispatched:
                    yield {
                        "type": "tool_result",
                        "tool": tc.name,
                        "tool_call_id": tc.id,
                        "result": result,
                        "truncated": isinstance(result, dict) and bool(result.get("truncated")),
                    }
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": self._serialize_tool_result(result),
                    })

                action, nudge_msg, nudged = self._token_budget_check(total_usage, nudged)
                if action == "stop":
                    self._status = AgentStatus.ERROR
                    yield {
                        "type": "done",
                        "content": {
                            "error": "token_budget_exceeded",
                            "used": self._used_tokens(total_usage),
                            "budget": self._token_budget,
                        },
                        "usage": total_usage,
                        "elapsed_ms": round(total_elapsed_ms, 2) if total_elapsed_ms else None,
                    }
                    return
                if nudge_msg:
                    messages.append({"role": "system", "content": nudge_msg})

            # 达到最大迭代
            self._status = AgentStatus.ERROR
            yield {
                "type": "done",
                "content": {"error": f"Agent '{self.name}' reached max iterations"},
                "usage": total_usage,
                "elapsed_ms": round(total_elapsed_ms, 2) if total_elapsed_ms else None,
            }

        except Exception as exc:
            self._status = AgentStatus.ERROR
            yield {"type": "done", "content": {"error": str(exc)}}
        finally:
            reset_notification_box(box_token)

    # ─── 消息构建 ───────────────────────────────────────────

    def _build_messages(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build LLM messages, preserving chat history when provided."""

        system_prompt = self.system_prompt

        persona_id = str(input_data.get("persona_id") or "").strip() or None
        session_id = str(input_data.get("session_id") or "").strip() or None
        persona = get_effective_persona(
            agent_name=self.name,
            session_id=session_id,
            persona_id=persona_id,
        )
        system_prompt = f"{system_prompt}\n\n{build_persona_prompt_block(persona)}"

        memory_context = str(input_data.get("memory_context") or "").strip()
        if memory_context:
            system_prompt = format_untrusted_memory_context(system_prompt, memory_context)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        conversation = self._coerce_conversation_messages(input_data)
        if conversation:
            messages.extend(conversation)
        else:
            messages.append({"role": "user", "content": self._build_user_message(input_data)})

        return messages

    @staticmethod
    def _coerce_conversation_messages(input_data: Dict[str, Any]) -> List[Dict[str, str]]:
        raw_messages = input_data.get("messages")
        if raw_messages is None:
            raw_messages = input_data.get("history")

        conversation: List[Dict[str, str]] = []
        if isinstance(raw_messages, list):
            for item in raw_messages[-30:]:
                if not isinstance(item, dict):
                    continue

                role = str(item.get("role") or item.get("type") or "").strip().lower()
                if role not in {"user", "assistant"}:
                    continue

                content = str(item.get("content") or "").strip()
                if not content:
                    continue

                conversation.append({"role": role, "content": content})

        current_message = str(input_data.get("message") or "").strip()
        if current_message:
            has_current = (
                bool(conversation)
                and conversation[-1]["role"] == "user"
                and conversation[-1]["content"] == current_message
            )
            if not has_current:
                conversation.append({"role": "user", "content": current_message})

        return conversation

    def _build_user_message(self, input_data: Dict[str, Any]) -> str:
        """将 input_data 格式化为用户消息"""
        if not input_data:
            return ""

        input_data = {
            key: value
            for key, value in input_data.items()
            if key not in {"messages", "history", "memory_context"}
        }
        if not input_data:
            return ""

        # 如果只有一个 key 且值是字符串，直接返回
        if len(input_data) == 1:
            value = next(iter(input_data.values()))
            if isinstance(value, str):
                return value

        # 多个字段时，按 key 分段展示
        parts = []
        for key, value in input_data.items():
            if isinstance(value, str):
                parts.append(f"## {key}\n{value}")
            else:
                parts.append(f"## {key}\n```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```")
        return "\n\n".join(parts)

    # ─── 输出解析 ───────────────────────────────────────────

    def _parse_output(self, content: str) -> Dict[str, Any]:
        """根据 output_format 解析 LLM 最终输出"""
        if self._output_format == "json":
            return self._parse_json(content)
        return {"response": content}

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        """JSON 解析，带 markdown 代码块清理和容错"""
        text = content.strip()

        # 移除 markdown 代码块标记
        if text.startswith("```"):
            lines = text.split("\n")
            # 跳过第一行（```json 或 ```）
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return {"data": result}
        except json.JSONDecodeError:
            return {"raw_response": content, "parse_error": True}

    # ─── Notification 回注（v2 Phase C 支柱 8）─────────────

    @staticmethod
    async def _drain_notifications(
        notification_box: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> None:
        """把累积的 dispatch_agent 完成事件转 `<task-notification>` user 消息塞回 messages。

        每轮 LLM 采样前调用；调用后清空 box。
        通过 ``await asyncio.sleep(0)`` 主动让出事件循环，给已派发的子任务一次
        推进/收尾的机会，避免必须等到下一轮 chat 才能看到 notification。
        """
        await asyncio.sleep(0)
        if not notification_box:
            return
        pending = list(notification_box)
        notification_box.clear()
        for payload in pending:
            messages.append(make_user_message(payload))

    # ─── Token 预算闸门 ────────────────────────────────────

    def _token_budget_check(
        self,
        total_usage: Dict[str, int],
        nudged: bool,
    ) -> Tuple[str, Optional[str], bool]:
        """检查是否触达 token 预算上限或 nudge 阈值。

        Returns:
            (action, nudge_message, new_nudged)
            - action: "continue" 或 "stop"
            - nudge_message: 非 None 时表示要在下一轮采样前 append 一条 system 消息
            - new_nudged: 更新后的 nudged 状态（避免重复插入）
        """
        if not self._token_budget:
            return "continue", None, nudged

        used = (total_usage.get("input_tokens", 0) or 0) + (total_usage.get("output_tokens", 0) or 0)
        if used >= self._token_budget:
            return "stop", None, nudged

        threshold = self._token_budget * self._token_budget_nudge_threshold
        if not nudged and used >= threshold:
            msg = build_token_budget_nudge(used, self._token_budget)
            return "continue", msg, True

        return "continue", None, nudged

    @staticmethod
    def _used_tokens(total_usage: Dict[str, int]) -> int:
        return (total_usage.get("input_tokens", 0) or 0) + (total_usage.get("output_tokens", 0) or 0)

    # ─── 工具调度（并发分组 + 权限校验 + Result Budget）──────

    async def _dispatch_tool_calls(
        self,
        tool_calls: List[ToolCall],
    ) -> List[Tuple[ToolCall, Any]]:
        """按 schema.is_concurrency_safe 分组执行 LLM 一轮请求的所有 tool_calls。

        - 可并发组用 ``asyncio.gather`` 并发执行
        - 串行组顺序执行（含找不到 tool 的项）
        - 返回值按 LLM 原始 ``tool_calls`` 顺序排列，方便消息历史保持稳定
        """
        if not tool_calls:
            return []

        tool_by_name: Dict[str, CapabilityBase] = {t.name: t for t in self._tools}

        concurrent: List[Tuple[int, ToolCall]] = []
        serial: List[Tuple[int, ToolCall]] = []
        for idx, tc in enumerate(tool_calls):
            tool = tool_by_name.get(tc.name)
            if tool is not None and self._safe_is_concurrent(tool):
                concurrent.append((idx, tc))
            else:
                serial.append((idx, tc))

        results: Dict[int, Any] = {}

        if concurrent:
            gathered = await asyncio.gather(
                *[self._execute_with_permission(tc, tool_by_name) for _, tc in concurrent]
            )
            for (idx, _), res in zip(concurrent, gathered):
                results[idx] = res

        for idx, tc in serial:
            results[idx] = await self._execute_with_permission(tc, tool_by_name)

        return [(tc, results[idx]) for idx, tc in enumerate(tool_calls)]

    async def _execute_with_permission(
        self,
        tool_call: ToolCall,
        tool_by_name: Dict[str, CapabilityBase],
    ) -> Any:
        """权限闸门 + 执行 + Result Budget 截断"""
        tool = tool_by_name.get(tool_call.name)
        if tool is None:
            return {"error": f"Tool '{tool_call.name}' not found"}

        try:
            schema = tool.get_schema()
        except Exception as exc:  # pragma: no cover — schema 异常视为不可执行
            return {"error": f"Tool '{tool_call.name}' schema unavailable: {exc}"}

        permit = await self._call_check_permissions(tool, tool_call.arguments)
        if permit.get("decision") != "allow":
            return {
                "error": f"Permission denied: {permit.get('reason') or 'denied by tool policy'}",
                "permission_denied": True,
            }

        try:
            raw = await tool.execute(**tool_call.arguments)
        except Exception as exc:
            logger.error(
                "Agent '%s' tool '%s' failed: %s",
                self.name,
                tool_call.name,
                exc,
            )
            return {"error": f"Tool '{tool_call.name}' execution failed: {exc}"}

        return self._apply_result_budget(raw, schema.max_result_size)

    @staticmethod
    async def _call_check_permissions(
        tool: CapabilityBase,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """调用 ``tool.check_permissions``，兼容同步与异步实现。"""
        fn = getattr(tool, "check_permissions", None)
        if fn is None:
            return {"decision": "allow"}
        try:
            outcome = fn(**arguments)
            if inspect.isawaitable(outcome):
                outcome = await outcome
        except Exception as exc:
            return {"decision": "deny", "reason": f"check_permissions raised: {exc}"}

        if not isinstance(outcome, dict):
            return {"decision": "allow"}
        return outcome

    @staticmethod
    def _apply_result_budget(result: Any, max_chars: int) -> Any:
        """单次工具结果超过预算时截断 + 标记 truncated。"""
        if not max_chars or max_chars <= 0:
            return result
        serialized = Agent._serialize_tool_result(result)
        if len(serialized) <= max_chars:
            return result
        return {
            "truncated": True,
            "original_size": len(serialized),
            "max_size": max_chars,
            "content": serialized[:max_chars]
            + f"\n... [truncated, original size {len(serialized)} chars]",
        }

    def _is_concurrent_safe(self, tool_call: ToolCall) -> bool:
        """供事件流标记 tool_call 是否在并发组里。"""
        for tool in self._tools:
            if tool.name == tool_call.name:
                return self._safe_is_concurrent(tool)
        return False

    @staticmethod
    def _safe_is_concurrent(tool: CapabilityBase) -> bool:
        try:
            return bool(tool.get_schema().is_concurrency_safe)
        except Exception:
            return False

    # ─── 单次工具执行（向后兼容旧 API；run/run_stream 已改用 _dispatch_tool_calls）──────

    async def _execute_tool(self, tool_call: ToolCall) -> Any:
        """单次执行某个工具（无权限闸门、无 Result Budget；保留供测试或外部调用）。"""
        for tool in self._tools:
            if tool.name == tool_call.name:
                try:
                    return await tool.execute(**tool_call.arguments)
                except Exception as exc:
                    logger.error(
                        "Agent '%s' tool '%s' failed: %s",
                        self.name,
                        tool_call.name,
                        exc,
                    )
                    return {"error": f"Tool '{tool_call.name}' execution failed: {str(exc)}"}

        return {"error": f"Tool '{tool_call.name}' not found"}

    @staticmethod
    def _serialize_tool_result(result: Any) -> str:
        """将工具执行结果序列化为字符串"""
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(result)

    @staticmethod
    def _attach_metrics(
        result: Dict[str, Any],
        usage: Dict[str, int],
        elapsed_ms: float,
    ) -> Dict[str, Any]:
        enriched = dict(result)
        if usage:
            enriched["usage"] = usage
        if elapsed_ms:
            enriched["elapsed_ms"] = round(elapsed_ms, 2)
        return enriched

    @staticmethod
    def _merge_usage(base: Dict[str, int], update: Optional[Dict[str, int]]) -> Dict[str, int]:
        if not update:
            return dict(base)

        merged = dict(base)
        for key, value in update.items():
            if key == "total_tokens" and ("input_tokens" in update or "output_tokens" in update):
                continue
            merged[key] = merged.get(key, 0) + int(value)
        if "input_tokens" in merged or "output_tokens" in merged:
            merged["total_tokens"] = merged.get("input_tokens", 0) + merged.get("output_tokens", 0)
        return merged

    # ─── 状态与元数据 ──────────────────────────────────────

    @property
    def status(self) -> AgentStatus:
        return self._status

    @status.setter
    def status(self, value: AgentStatus) -> None:
        self._status = value

    async def start(self) -> None:
        """启动 Agent"""
        self._status = AgentStatus.IDLE

    async def stop(self) -> None:
        """停止 Agent"""
        self._status = AgentStatus.STOPPED

    def get_capabilities(self) -> List[str]:
        """返回该 Agent 持有的工具名称列表"""
        return [t.name for t in self._tools]

    def get_metadata(self) -> AgentMetadata:
        """返回 Agent 元数据"""
        return AgentMetadata(
            name=self.name,
            description=self._description,
            capabilities=self.get_capabilities(),
            status=self._status,
        )
