"""审查 Agent - 接收代码，进行专业代码审查

支持:
- 接收 CoderAgent 生成的代码
- 调用 LLM 进行多维度代码审查
- 输出结构化的审查结果
- 根据审查结论发射 review_passed 或 review_failed 事件
"""
import json
from typing import Any, Dict
from core.agent import BaseAgent, AgentMetadata
from core.llm import BaseLLMClient


REVIEWER_SYSTEM_PROMPT = """\
你是一位严格且经验丰富的代码审查专家。

## 审查维度
1. **正确性** - 代码逻辑是否正确，是否有 bug
2. **安全性** - 是否存在安全漏洞（注入、XSS、敏感信息泄露等）
3. **可维护性** - 代码结构是否清晰，命名是否规范，是否易于理解
4. **性能** - 是否有明显的性能问题（不必要的循环、内存泄漏等）
5. **最佳实践** - 是否遵循语言和框架的最佳实践
6. **错误处理** - 异常处理是否完善，边界情况是否考虑

## 审查标准
- 严重问题（安全漏洞、崩溃 bug）：必须驳回
- 中等问题（性能问题、代码风格）：酌情决定
- 轻微问题（命名建议、可选优化）：可以通过但需建议

## 输出格式
你必须严格以 JSON 格式输出，不要包含任何 markdown 代码块标记，直接输出纯 JSON：
{
    "approved": true 或 false,
    "issues": [
        {
            "type": "bug|security|performance|style|logic",
            "description": "问题描述",
            "line_hint": "相关代码片段或位置提示",
            "severity": "critical|major|minor"
        }
    ],
    "suggestions": [
        "改进建议1",
        "改进建议2"
    ],
    "severity": 1到10的整数，10表示问题最严重,
    "summary": "审查总结"
}

注意：
- approved 为 true 表示代码可以通过审查
- severity 为整体严重程度评分：1-3 轻微，4-6 中等，7-10 严重
- issues 列表为空时 approved 应为 true
- 只输出 JSON，不要有任何额外文字
"""


class ReviewerAgent(BaseAgent):
    """审查 Agent - 调用 LLM 审查代码，输出结构化审查结果"""

    def __init__(self, name: str, bus, llm_client: BaseLLMClient):
        super().__init__(
            name,
            bus,
            description="审查智能体 - 多维度代码审查，输出结构化报告",
            capabilities=["code_review", "quality_analysis"],
        )
        self.llm = llm_client

    async def on_event(self, event):
        """响应事件，审查代码后根据结果发射不同事件"""
        result = await self.process(event.data)
        if result:
            if result.get("approved", False):
                await self.emit("review_passed", result)
            else:
                await self.emit("review_failed", result)

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理代码审查请求"""
        raw_code = data.get("code", "")

        # 如果 code 是来自 coder agent 的 dict 输出，提取其字段
        if isinstance(raw_code, dict):
            code = raw_code.get("code", "")
            language = raw_code.get("language", data.get("language", "unknown"))
            file_path = raw_code.get("file_path", data.get("file_path", ""))
            task = raw_code.get("task", raw_code.get("description", data.get("task", data.get("description", ""))))
        else:
            code = raw_code
            language = data.get("language", "unknown")
            file_path = data.get("file_path", "")
            task = data.get("task", data.get("description", data.get("message", "")))

        # 构建用户提示
        user_content = "## 待审查代码\n"
        if file_path:
            user_content += f"文件路径: `{file_path}`\n"
        if language != "unknown":
            user_content += f"编程语言: {language}\n"
        if task:
            user_content += f"\n## 任务描述\n{task}\n"
        user_content += f"\n```{language}\n{code}\n```"

        messages = [
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = await self.llm.chat(messages)

        # 解析 LLM 返回的 JSON 结果
        review_result = self._parse_response(response)

        return {
            "code": code,
            "language": language,
            "file_path": file_path,
            **review_result,
        }

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 的 JSON 响应，带容错处理"""
        text = response.strip()

        # 移除可能的 markdown 代码块标记
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            parsed = json.loads(text)
            return {
                "approved": bool(parsed.get("approved", False)),
                "issues": parsed.get("issues", []),
                "suggestions": parsed.get("suggestions", []),
                "severity": int(parsed.get("severity", 5)),
                "summary": parsed.get("summary", ""),
            }
        except (json.JSONDecodeError, ValueError):
            # 解析失败时，保守处理 —— 不通过审查
            return {
                "approved": False,
                "issues": [
                    {
                        "type": "logic",
                        "description": "审查结果解析失败，需要人工复核",
                        "line_hint": "",
                        "severity": "major",
                    }
                ],
                "suggestions": ["建议重新提交审查"],
                "severity": 5,
                "summary": "LLM 返回非结构化内容，无法自动判定",
            }
