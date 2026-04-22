"""通用配置化 Agent — 行为完全由 YAML 定义

核心特性:
- 所有行为（system_prompt, tools, output_format）由配置驱动
- 内置 tool_use 循环：LLM 自主决定调用哪些工具
- 支持流式传输：run_stream() 逐步 yield 中间事件
- 新增 Agent 只需在 agents.yaml 加一条记录，零代码
"""
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from ..llm.base import BaseLLMClient, LLMResponse, LLMStreamEvent, ToolCall
from ..capability.base import CapabilityBase

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
    ):
        self.name = name
        self.llm = llm_client
        self.system_prompt = system_prompt
        self._tools = tools or []
        self._output_format = output_format
        self._max_iterations = max_iterations
        self._description = description
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
        try:
            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_user_message(input_data)},
            ]
            tool_schemas = [t.get_schema() for t in self._tools]

            for iteration in range(self._max_iterations):
                response = await self.llm.chat(
                    messages,
                    tools=tool_schemas if tool_schemas else None,
                )

                # LLM 返回最终文本 → 结束循环
                if response.stop_reason != "tool_use":
                    self._status = AgentStatus.IDLE
                    return self._parse_output(response.content or "")

                # LLM 请求工具调用 → 执行工具 → 继续循环
                # 先添加 assistant 消息（含 tool_calls）
                assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": response.tool_calls}
                if response.content:
                    assistant_msg["content"] = response.content
                messages.append(assistant_msg)

                for tc in response.tool_calls:
                    result = await self._execute_tool(tc)
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

            # 达到最大迭代次数
            self._status = AgentStatus.ERROR
            logger.warning(
                "Agent '%s' reached max iterations (%d)",
                self.name,
                self._max_iterations,
            )
            return {"error": f"Agent '{self.name}' reached max iterations ({self._max_iterations})"}

        except Exception as exc:
            self._status = AgentStatus.ERROR
            logger.error("Agent '%s' failed: %s", self.name, exc)
            raise

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
        try:
            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_user_message(input_data)},
            ]
            tool_schemas = [t.get_schema() for t in self._tools]

            for iteration in range(self._max_iterations):
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

                # LLM 返回最终文本 → 结束
                if stop_reason != "tool_use":
                    self._status = AgentStatus.IDLE
                    result = self._parse_output(full_text)
                    yield {"type": "done", "content": result}
                    return

                # 工具调用
                assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
                if full_text:
                    assistant_msg["content"] = full_text
                messages.append(assistant_msg)

                for tc in tool_calls:
                    yield {"type": "tool_call", "tool": tc.name, "args": tc.arguments}
                    result = await self._execute_tool(tc)
                    yield {"type": "tool_result", "tool": tc.name, "result": result}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": self._serialize_tool_result(result),
                    })

            # 达到最大迭代
            self._status = AgentStatus.ERROR
            yield {"type": "done", "content": {"error": f"Agent '{self.name}' reached max iterations"}}

        except Exception as exc:
            self._status = AgentStatus.ERROR
            yield {"type": "done", "content": {"error": str(exc)}}

    # ─── 消息构建 ───────────────────────────────────────────

    def _build_user_message(self, input_data: Dict[str, Any]) -> str:
        """将 input_data 格式化为用户消息"""
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

    # ─── 工具执行 ───────────────────────────────────────────

    async def _execute_tool(self, tool_call: ToolCall) -> Any:
        """查找并执行工具"""
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
