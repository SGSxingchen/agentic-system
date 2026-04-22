"""工作流编排器 - 顺序 / 并行 / YAML 工作流执行

WorkflowOrchestrator 接收 agent_registry 和 bus，
协调多个 Agent 按照指定的工作流定义执行任务。
"""
import asyncio
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..agent.registry import AgentRegistry
from ..bus import SimpleBus
from .types import Task, TaskResult, WorkflowResult, WorkflowStatus


class WorkflowOrchestrator:
    """工作流编排器

    Usage::

        orchestrator = WorkflowOrchestrator(agent_registry, bus)

        # 顺序执行
        result = await orchestrator.execute_sequential([task1, task2])

        # 并行执行
        results = await orchestrator.execute_parallel([task1, task2])

        # 从配置执行
        result = await orchestrator.execute_workflow({
            "name": "code_review",
            "mode": "sequential",
            "steps": [...]
        })
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        bus: SimpleBus,
    ) -> None:
        self._registry = agent_registry
        self._bus = bus

    # ─── 顺序执行 ─────────────────────────────────────────

    async def execute_sequential(
        self,
        tasks: List[Task],
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowResult:
        """顺序执行任务列表

        每个任务的输出通过 output_key 保存到上下文，
        下一个任务可以通过 ${key} 引用。

        Args:
            tasks: 任务列表
            initial_context: 初始上下文

        Returns:
            WorkflowResult
        """
        result = WorkflowResult(
            status=WorkflowStatus.RUNNING,
            context=dict(initial_context or {}),
            started_at=datetime.now(),
        )
        start_time = time.monotonic()

        for task in tasks:
            task_result = await self._execute_task(task, result.context)
            result.task_results.append(task_result)

            if task_result.status == WorkflowStatus.FAILED:
                result.status = WorkflowStatus.FAILED
                result.error = f"Task '{task.name}' failed: {task_result.error}"
                break

            # 将输出存入上下文
            if task.output_key and task_result.output:
                result.context[task.output_key] = task_result.output

        else:
            # 所有任务成功完成
            result.status = WorkflowStatus.COMPLETED

        result.completed_at = datetime.now()
        result.duration_ms = (time.monotonic() - start_time) * 1000
        return result

    # ─── 并行执行 ─────────────────────────────────────────

    async def execute_parallel(
        self,
        tasks: List[Task],
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowResult:
        """并行执行任务列表

        所有任务同时启动，互不依赖。

        Args:
            tasks: 任务列表
            initial_context: 共享初始上下文

        Returns:
            WorkflowResult
        """
        result = WorkflowResult(
            status=WorkflowStatus.RUNNING,
            context=dict(initial_context or {}),
            started_at=datetime.now(),
        )
        start_time = time.monotonic()

        # 并行启动所有任务
        coros = [
            self._execute_task(task, result.context)
            for task in tasks
        ]
        task_results = await asyncio.gather(*coros, return_exceptions=True)

        has_failure = False
        for task, tr in zip(tasks, task_results):
            if isinstance(tr, Exception):
                tr = TaskResult(
                    task_name=task.name,
                    status=WorkflowStatus.FAILED,
                    error=str(tr),
                )
                has_failure = True
            else:
                if tr.status == WorkflowStatus.FAILED:
                    has_failure = True
                if task.output_key and tr.output:
                    result.context[task.output_key] = tr.output
            result.task_results.append(tr)

        result.status = WorkflowStatus.FAILED if has_failure else WorkflowStatus.COMPLETED
        result.completed_at = datetime.now()
        result.duration_ms = (time.monotonic() - start_time) * 1000
        return result

    # ─── 从配置执行工作流 ──────────────────────────────────

    async def execute_workflow(
        self,
        workflow_config: Dict[str, Any],
    ) -> WorkflowResult:
        """从 dict/YAML 配置执行工作流

        配置格式::

            {
                "name": "code_review",
                "mode": "sequential",  # sequential | parallel
                "steps": [
                    {"name": "plan", "agent": "planner", "output_key": "plan"},
                    {"name": "code", "agent": "coder", "input": {"plan": "${plan}"},
                     "output_key": "code"},
                    {"name": "review", "agent": "reviewer",
                     "input": {"code": "${code}"},
                     "condition": "code is not None",
                     "max_iterations": 3},
                ]
            }
        """
        steps = workflow_config.get("steps", [])
        mode = workflow_config.get("mode", "sequential")
        initial_context = workflow_config.get("context", {})

        tasks = [self._parse_task(step) for step in steps]

        if mode == "parallel":
            return await self.execute_parallel(tasks, initial_context)
        else:
            return await self.execute_sequential(tasks, initial_context)

    # ─── 内部方法 ─────────────────────────────────────────

    async def _execute_task(
        self,
        task: Task,
        context: Dict[str, Any],
    ) -> TaskResult:
        """执行单个任务"""
        task_result = TaskResult(
            task_name=task.name,
            started_at=datetime.now(),
        )
        start_time = time.monotonic()

        # 条件检查
        if task.condition:
            if not self._evaluate_condition(task.condition, context):
                task_result.status = WorkflowStatus.SKIPPED
                task_result.completed_at = datetime.now()
                task_result.duration_ms = (time.monotonic() - start_time) * 1000
                return task_result

        # 查找 Agent
        agent = self._registry.get(task.agent)
        if agent is None:
            task_result.status = WorkflowStatus.FAILED
            task_result.error = f"Agent '{task.agent}' not found in registry"
            task_result.completed_at = datetime.now()
            task_result.duration_ms = (time.monotonic() - start_time) * 1000
            return task_result

        # 解析输入（变量替换）
        input_data = self._resolve_variables(task.input_data or {}, context)

        # 迭代执行
        task_result.status = WorkflowStatus.RUNNING
        iteration = 0
        max_iter = max(task.max_iterations, 1)

        while iteration < max_iter:
            iteration += 1
            task_result.iterations = iteration

            try:
                output = await agent.process(input_data)
                task_result.output = output
                task_result.status = WorkflowStatus.COMPLETED
                break
            except Exception as e:
                task_result.error = str(e)
                if iteration >= max_iter:
                    task_result.status = WorkflowStatus.FAILED
                else:
                    # 还有重试机会，将错误信息添加到输入中
                    input_data["_previous_error"] = str(e)

        task_result.completed_at = datetime.now()
        task_result.duration_ms = (time.monotonic() - start_time) * 1000
        return task_result

    @staticmethod
    def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
        """评估条件表达式

        在 context 的命名空间中执行 Python 表达式。
        出错时默认返回 False（跳过该步骤）。
        """
        try:
            return bool(eval(condition, {"__builtins__": {}}, context))
        except Exception:
            return False

    @staticmethod
    def _resolve_variables(
        data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """解析 ${variable} 变量引用

        支持嵌套引用：值为字符串且包含 ${key} 时，
        如果整个值是 ${key} 则替换为原始类型，
        否则做字符串插值。
        """
        resolved: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                resolved[key] = _substitute(value, context)
            elif isinstance(value, dict):
                resolved[key] = WorkflowOrchestrator._resolve_variables(value, context)
            else:
                resolved[key] = value
        return resolved

    @staticmethod
    def _parse_task(step: Dict[str, Any]) -> Task:
        """从 dict 配置解析 Task"""
        return Task(
            name=step["name"],
            agent=step["agent"],
            input_data=step.get("input"),
            output_key=step.get("output_key"),
            condition=step.get("condition"),
            max_iterations=step.get("max_iterations", 1),
            timeout=step.get("timeout"),
        )


# ─── 辅助函数 ─────────────────────────────────────────────

_VAR_PATTERN = re.compile(r"\$\{(\w+)}")


def _substitute(template: str, context: Dict[str, Any]) -> Any:
    """替换 ${var} 引用

    如果整个字符串恰好是 ${key}，返回 context[key] 的原始类型。
    否则进行字符串插值。
    """
    # 完全匹配 → 原始类型
    match = re.fullmatch(r"\$\{(\w+)}", template)
    if match:
        key = match.group(1)
        return context.get(key, template)

    # 部分匹配 → 字符串插值
    def replacer(m: re.Match) -> str:
        return str(context.get(m.group(1), m.group(0)))

    return _VAR_PATTERN.sub(replacer, template)
