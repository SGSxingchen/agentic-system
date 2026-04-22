"""任务规划智能体 - 将用户需求分解为结构化的子任务计划

支持:
- 接收用户需求描述
- 调用 LLM 将需求分解为多个子任务
- 输出结构化的任务计划（JSON 格式）
- 发射 "plan_created" 事件
"""
import json
from typing import Any, Dict, List, Optional
from core.agent import BaseAgent, AgentMetadata
from core.llm import BaseLLMClient


# LLM 系统提示：引导模型输出结构化的任务计划
PLANNER_SYSTEM_PROMPT = """\
你是一个任务规划智能体，负责将用户的需求分解为具体的、可执行的子任务计划。

你必须严格按照以下 JSON 格式输出任务计划，不要输出任何其他内容：

```json
{
  "tasks": [
    {
      "name": "子任务名称（简短英文标识，如 design_api）",
      "description": "子任务的详细描述",
      "agent": "执行该任务的智能体名称（planner/coder/reviewer/tester）",
      "dependencies": ["依赖的其他子任务 name，没有则为空数组"],
      "priority": 1
    }
  ]
}
```

规则：
1. 每个子任务的 name 必须唯一，使用 snake_case 命名
2. agent 字段指定由哪个智能体执行：
   - "coder": 代码生成、代码修改
   - "reviewer": 代码审查、质量检查
   - "tester": 测试编写、测试执行
   - "planner": 需要进一步拆分的复杂子任务
3. dependencies 是一个数组，包含当前任务依赖的其他子任务的 name
4. priority 是优先级，数字越小优先级越高（1 最高）
5. 任务分解应当合理，既不过于粗粒度也不过于细粒度
6. 确保依赖关系合理，不能出现循环依赖
7. 只输出 JSON，不要输出解释文字
"""


class PlannerAgent(BaseAgent):
    """任务规划智能体 - 将需求分解为结构化的子任务计划"""

    def __init__(
        self,
        name: str,
        bus,
        llm_client: BaseLLMClient,
        max_retries: int = 2,
    ):
        super().__init__(
            name,
            bus,
            description="任务规划智能体 - 将需求分解为结构化子任务计划",
            capabilities=["task_decomposition", "planning"],
        )
        self.llm = llm_client
        self.max_retries = max_retries

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理用户需求，生成任务计划

        Args:
            data: 包含 "requirement" 字段的字典

        Returns:
            包含 "plan"（任务列表）和 "requirement"（原始需求）的字典
        """
        requirement = data.get("requirement", "")
        if not requirement:
            return {"error": "缺少需求描述", "plan": None}

        # 调用 LLM 生成计划
        plan = await self._generate_plan(requirement)

        if plan is None:
            return {
                "error": "无法生成有效的任务计划",
                "requirement": requirement,
                "plan": None,
            }

        result = {
            "requirement": requirement,
            "plan": plan,
        }

        # 发射 plan_created 事件
        await self.emit("plan_created", result)

        return result

    async def _generate_plan(
        self, requirement: str
    ) -> Optional[List[Dict[str, Any]]]:
        """调用 LLM 生成并解析任务计划

        支持重试机制：如果 LLM 返回的内容无法解析为合法 JSON，
        会重试最多 max_retries 次。
        """
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": requirement},
        ]

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.llm.chat(messages)
                tasks = self._parse_plan(response)
                if tasks is not None:
                    return tasks
            except Exception as e:
                print(f"[WARN] PlannerAgent 第 {attempt + 1} 次尝试失败: {e}")

        return None

    def _parse_plan(self, response: str) -> Optional[List[Dict[str, Any]]]:
        """解析 LLM 响应为任务列表

        尝试从响应中提取 JSON，支持带 markdown 代码块的格式。
        """
        text = response.strip()

        # 去除 markdown 代码块标记
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉第一行（```json）和最后一行（```）
            lines = [
                line for line in lines
                if not line.strip().startswith("```")
            ]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        # 支持 {"tasks": [...]} 格式
        if isinstance(data, dict) and "tasks" in data:
            tasks = data["tasks"]
        elif isinstance(data, list):
            tasks = data
        else:
            return None

        # 校验每个子任务的必要字段
        validated = []
        for task in tasks:
            if not isinstance(task, dict):
                return None
            if "name" not in task or "description" not in task:
                return None
            validated.append({
                "name": task["name"],
                "description": task["description"],
                "agent": task.get("agent", "coder"),
                "dependencies": task.get("dependencies", []),
                "priority": task.get("priority", 5),
            })

        if not validated:
            return None

        return validated
