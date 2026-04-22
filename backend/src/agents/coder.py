"""编码 Agent - 接收任务描述，生成代码

支持:
- 接收 PlannerAgent 分解的子任务
- 调用 LLM 生成高质量代码
- 输出结构化的代码结果
- 发射 code_generated 事件供 ReviewerAgent 消费
"""
import json
from typing import Any, Dict
from core.agent import BaseAgent, AgentMetadata
from core.llm import BaseLLMClient


CODER_SYSTEM_PROMPT = """\
你是一位资深软件工程师，专精于高质量代码生成。

## 工作流程
1. 分析用户给出的任务描述，理解需求与上下文
2. 选择最合适的编程语言和技术方案
3. 编写清晰、可维护、符合最佳实践的代码

## 代码质量要求
- 遵循所选语言的编码规范和惯用写法
- 包含必要的类型注解和文档字符串
- 合理的错误处理和边界情况考虑
- 函数/类职责单一，避免过度设计
- 变量和函数命名清晰有意义

## 输出格式
你必须严格以 JSON 格式输出，不要包含任何 markdown 代码块标记，直接输出纯 JSON：
{
    "code": "完整的代码内容",
    "language": "编程语言（如 python, javascript, java 等）",
    "file_path": "建议的文件路径（如 src/utils/helper.py）",
    "description": "简要说明代码的功能和设计思路"
}

注意：
- code 字段中的换行用 \\n 表示
- 只输出 JSON，不要有任何额外文字
"""


class CoderAgent(BaseAgent):
    """编码 Agent - 调用 LLM 生成代码，输出结构化结果"""

    def __init__(self, name: str, bus, llm_client: BaseLLMClient):
        super().__init__(
            name,
            bus,
            description="编码智能体 - 调用 LLM 生成高质量代码",
            capabilities=["code_generation"],
        )
        self.llm = llm_client

    async def on_event(self, event):
        """响应事件，生成代码后发射 code_generated 事件"""
        result = await self.process(event.data)
        if result:
            await self.emit("code_generated", result)

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理任务描述，调用 LLM 生成代码"""
        task_description = data.get("task", data.get("message", data.get("requirement", "")))

        # 如果有 plan 数据，将其转为上下文文本
        plan = data.get("plan")
        if plan and not task_description:
            # plan 可能是 dict（来自 planner 的输出）
            if isinstance(plan, dict):
                req = plan.get("requirement", "")
                tasks = plan.get("plan", [])
                task_description = req
                if isinstance(tasks, list):
                    plan_text = "\n".join(
                        f"- {t.get('name', '')}: {t.get('description', '')}" for t in tasks if isinstance(t, dict)
                    )
                    data["context"] = data.get("context", "") + f"\n\n## 任务计划\n{plan_text}"
            elif isinstance(plan, str):
                task_description = plan

        context = data.get("context", "")
        requirements = data.get("requirements", "")

        # 构建用户提示
        user_content = f"## 任务描述\n{task_description}"
        if context:
            user_content += f"\n\n## 上下文信息\n{context}"
        if requirements:
            user_content += f"\n\n## 额外要求\n{requirements}"

        messages = [
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = await self.llm.chat(messages)

        # 解析 LLM 返回的 JSON 结果
        code_result = self._parse_response(response)

        return {
            "task": task_description,
            **code_result,
        }

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 的 JSON 响应，带容错处理"""
        # 尝试清理常见格式问题
        text = response.strip()

        # 移除可能的 markdown 代码块标记
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # 去掉开头
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # 去掉结尾
            text = "\n".join(lines)

        try:
            parsed = json.loads(text)
            return {
                "code": parsed.get("code", ""),
                "language": parsed.get("language", "unknown"),
                "file_path": parsed.get("file_path", ""),
                "description": parsed.get("description", ""),
            }
        except json.JSONDecodeError:
            # 解析失败时，将原始响应作为代码返回
            return {
                "code": response,
                "language": "unknown",
                "file_path": "",
                "description": "LLM 返回非结构化内容，已作为原始代码保留",
            }
