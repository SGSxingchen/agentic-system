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
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ..llm.base import BaseLLMClient, LLMResponse, LLMStreamEvent, ToolCall
from ..capability.base import CapabilityBase
from ..task.context import (
    set_notification_box,
    reset_notification_box,
    set_workspace_root_override,
    reset_workspace_root_override,
    get_parent_task_id,
)
from ..task.notifications import make_user_message
from ..workspace import WorkspaceNotFoundError, WorkspaceStore
from ..prompts import (
    build_token_budget_nudge,
    format_untrusted_memory_context,
    format_workspace_system_context,
)
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
    runtime_config: Dict[str, Any] = field(default_factory=dict)


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
        workspace_token = self._maybe_set_workspace_root(input_data)
        try:
            messages = self._build_messages(input_data)
            # Spec 2 §10.2 / Task 14 — 调用方可通过 input_data['_excluded_tools']
            # 临时屏蔽部分工具（不修改 self._tools，仅影响本次 run）。
            excluded = set(input_data.get("_excluded_tools") or [])
            active_tools = (
                [t for t in self._tools if t.name not in excluded]
                if excluded
                else list(self._tools)
            )
            tool_schemas = [t.get_schema() for t in active_tools]
            total_usage: Dict[str, int] = {}
            total_elapsed_ms = 0.0
            nudged = False

            for iteration in range(self._max_iterations):
                await self._drain_notifications(notification_box, messages)
                # A6: 注入 on_retry 闭包推 progress.retry_count（仅当任务上下文存在）
                on_retry_cb = self._build_on_retry_callback()
                response = await self.llm.chat(
                    messages,
                    tools=tool_schemas if tool_schemas else None,
                    on_retry=on_retry_cb,
                )
                # 调用成功 → 重置 retry_count（避免前端卡在"重试中"）
                self._reset_retry_progress()
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
            if workspace_token is not None:
                reset_workspace_root_override(workspace_token)
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
        workspace_token = self._maybe_set_workspace_root(input_data)
        try:
            messages = self._build_messages(input_data)
            # Spec 2 §10.2 / Task 14 — 通过 input_data['_excluded_tools'] 临时屏蔽工具
            excluded = set(input_data.get("_excluded_tools") or [])
            active_tools = (
                [t for t in self._tools if t.name not in excluded]
                if excluded
                else list(self._tools)
            )
            tool_schemas = [t.get_schema() for t in active_tools]
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
                    on_retry=self._build_on_retry_callback(),
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
                # A6: 流式建立成功 → 重置 retry_count
                self._reset_retry_progress()

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
            if workspace_token is not None:
                reset_workspace_root_override(workspace_token)
            reset_notification_box(box_token)

    @staticmethod
    def _maybe_set_workspace_root(input_data: Dict[str, Any]):
        raw_root = str(input_data.get("_trusted_workspace_root") or "").strip()
        if not raw_root:
            workspace_id = str(input_data.get("workspace_id") or "").strip()
            if not workspace_id:
                return None
            try:
                raw_root = WorkspaceStore().get(workspace_id).root_path
            except WorkspaceNotFoundError:
                return None
        return set_workspace_root_override(Path(raw_root))

    # ─── 消息构建 ───────────────────────────────────────────

    def _build_messages(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build LLM messages, preserving chat history when provided."""

        system_prompt = format_workspace_system_context(
            self.system_prompt,
            agent_name=self.name,
            workspace_id=str(input_data.get("workspace_id") or "").strip() or None,
            workspace_root=str(input_data.get("_trusted_workspace_root") or "").strip() or None,
            session_id=str(input_data.get("session_id") or "").strip() or None,
        )

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

        # B1 Plan 3 P3 Task 25 — 附件 system reminder。非图片附件由 routes 层
        # 预先建好工作区软链/拷贝并拼好 <attached_files> 块；这里直接追加到
        # system prompt 末尾，让 Agent 自助用 read_file 读取。
        attachment_context = str(input_data.get("attachment_context") or "").strip()
        if attachment_context:
            system_prompt = f"{system_prompt}\n\n{attachment_context}"

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        conversation = self._coerce_conversation_messages(input_data)
        if conversation:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "[当前会话历史]\n"
                        f"下面紧接着的 {len(conversation)} 条 user/assistant 消息来自同一个聊天会话，"
                        "是本轮回答必须优先参考的上下文。"
                        "如果用户询问“上下文”“刚才”“前面说了什么”等问题，"
                        "请优先概括这些会话历史里的具体内容，而不是只复述系统规则、人格或长期记忆。"
                    ),
                }
            )
            messages.extend(conversation)
        else:
            messages.append({"role": "user", "content": self._build_user_message(input_data)})

        # B1 Plan 3 P3 Task 26 — 图片附件走 vision payload。把 attachment_images
        # 列表里的项打包成中立 image block 追加到最后一条 user 消息上。LLM
        # 客户端层负责把中立块翻译成 OpenAI image_url / Anthropic image source。
        attachment_images = input_data.get("attachment_images")
        if isinstance(attachment_images, list) and attachment_images:
            self._append_image_blocks_to_last_user(messages, attachment_images)

        return messages

    @staticmethod
    def _append_image_blocks_to_last_user(
        messages: List[Dict[str, Any]],
        images: List[Dict[str, Any]],
    ) -> None:
        """Inject neutral image blocks into the most recent user message."""

        target: Optional[Dict[str, Any]] = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                target = msg
                break
        if target is None:
            target = {"role": "user", "content": ""}
            messages.append(target)

        existing = target.get("content")
        if isinstance(existing, list):
            parts: List[Any] = list(existing)
        else:
            text = str(existing or "").strip()
            parts = [{"type": "text", "text": text}] if text else []

        for img in images:
            if not isinstance(img, dict):
                continue
            data = img.get("data") or ""
            url = img.get("url") or ""
            if not data and not url:
                continue
            block: Dict[str, Any] = {
                "type": "image",
                "mime_type": str(img.get("mime_type") or "image/png"),
            }
            if data:
                block["data"] = str(data)
            if url:
                block["url"] = str(url)
            parts.append(block)

        if not parts:
            return
        # If we only ended up with a text part (no images survived), keep
        # the original string form to avoid an unneeded shape change.
        only_text = (
            len(parts) == 1
            and isinstance(parts[0], dict)
            and parts[0].get("type") == "text"
        )
        if only_text:
            target["content"] = str(parts[0].get("text") or "")
        else:
            target["content"] = parts

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
            if key not in {"messages", "history", "memory_context", "attachment_context", "attachment_images", "workspace_root", "_trusted_workspace_root"}
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

    # ─── A6: LLM 重试 → progress.retry_count 桥 ─────────────

    def _build_on_retry_callback(self):
        """构造 on_retry 闭包：把当前重试尝试号写到 TaskRegistry.progress。

        仅当协程上下文中有 ``parent_task_id`` + 全局 ``task_registry`` 可用时返回回调；
        否则返回 None，让 ``call_with_retry`` 跳过通知（不影响纯单元测试场景）。
        """
        try:
            task_id = get_parent_task_id()
        except Exception:
            return None
        if not task_id:
            return None
        try:
            from api.dependencies import get_task_registry  # 延迟 import 防循环
        except Exception:
            return None
        registry = get_task_registry()
        if registry is None or task_id not in registry:
            return None
        max_retries = int(self._runtime_config.get("max_retries") or 3)

        def _on_retry(attempt: int, exc: BaseException, sleep_for: float) -> None:
            try:
                registry.set_progress(
                    task_id,
                    retry_count=attempt,
                    activity=f"重试中 ({attempt}/{max_retries})",
                )
            except Exception:  # pragma: no cover — 回调异常吞掉
                pass

        return _on_retry

    def _reset_retry_progress(self) -> None:
        """LLM 调用成功后把 retry_count 显式置 0（覆盖语义）。"""
        try:
            task_id = get_parent_task_id()
        except Exception:
            return
        if not task_id:
            return
        try:
            from api.dependencies import get_task_registry
        except Exception:
            return
        registry = get_task_registry()
        if registry is None or task_id not in registry:
            return
        # 仅当 retry_count > 0 时才写，避免每轮都打 set_progress 开销
        state = registry.get(task_id)
        if state and state.progress.retry_count > 0:
            registry.set_progress(task_id, retry_count=0)

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
            runtime_config=dict(self._runtime_config or {}),
        )
