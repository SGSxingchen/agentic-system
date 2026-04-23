"""Pipeline — 统一的任务编排引擎

替代旧版三套编排机制（bus 订阅链 / EventEngine / WorkflowOrchestrator），
提供单一的 Pipeline.execute() 入口。

所有执行通过 CapabilityRegistry.execute() 路由，
Agent 和工具能力对 Pipeline 来说是统一的。
"""
import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..capability.registry import CapabilityRegistry
from .types import (
    PipelineConfig,
    PipelineResult,
    PipelineStatus,
    PipelineStep,
    StepResult,
)

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r"\$\{(\w+)}")


class Pipeline:
    """统一任务编排引擎

    Usage::

        pipeline = Pipeline(cap_registry, bus)
        pipeline.load_templates(yaml_config)

        result = await pipeline.execute(
            config=pipeline.get_template("code_generation_and_review"),
            initial_context={"user_requirement": "实现一个排序函数"},
        )
    """

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        bus: Optional[Any] = None,
    ) -> None:
        self._capabilities = capability_registry
        self._bus = bus
        self._templates: Dict[str, Dict[str, Any]] = {}

    # ─── 模板管理 ──────────────────────────────────────────

    def load_templates(self, config: Dict[str, Any]) -> None:
        """从 YAML 配置加载管线模板"""
        if isinstance(config, dict):
            self._templates = config
            logger.info("已加载 %d 个管线模板", len(config))

    def get_template(self, name: str) -> Optional[PipelineConfig]:
        """获取管线模板并解析为 PipelineConfig"""
        template = self._templates.get(name)
        if not template:
            return None
        return self._parse_config(name, template)

    def list_templates(self) -> Dict[str, Any]:
        """列出所有模板"""
        return dict(self._templates)

    # ─── 执行 ──────────────────────────────────────────────

    async def execute(
        self,
        config: PipelineConfig,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """执行管线

        Args:
            config: 管线配置
            initial_context: 初始上下文变量

        Returns:
            PipelineResult 包含所有步骤结果和最终上下文
        """
        result = PipelineResult(
            status=PipelineStatus.RUNNING,
            context=dict(initial_context or {}),
            started_at=datetime.now(),
        )
        start_time = time.monotonic()

        logger.info("开始执行管线: %s (mode=%s, steps=%d)", config.name, config.mode, len(config.steps))

        try:
            if config.mode == "parallel":
                await self._execute_parallel(config.steps, result)
            else:
                await self._execute_sequential(config.steps, result)
        except Exception as exc:
            result.status = PipelineStatus.FAILED
            result.error = str(exc)
            logger.error("管线 '%s' 执行异常: %s", config.name, exc)

        result.completed_at = datetime.now()
        result.duration_ms = (time.monotonic() - start_time) * 1000

        if result.status == PipelineStatus.RUNNING:
            result.status = PipelineStatus.COMPLETED

        logger.info(
            "管线 '%s' 执行完成: %s (%.1fms)",
            config.name,
            result.status.value,
            result.duration_ms,
        )
        return result

    # ─── 顺序执行 ─────────────────────────────────────────

    async def _execute_sequential(
        self, steps: List[PipelineStep], result: PipelineResult
    ) -> None:
        """顺序执行步骤"""
        for step in steps:
            step_result = await self._execute_step(step, result.context)
            result.step_results.append(step_result)

            if step_result.status == PipelineStatus.FAILED:
                result.status = PipelineStatus.FAILED
                result.error = f"Step '{step.name}' failed: {step_result.error}"
                break

            # 输出存入上下文
            if step.output_key and step_result.output:
                result.context[step.output_key] = step_result.output

    # ─── 并行执行 ─────────────────────────────────────────

    async def _execute_parallel(
        self, steps: List[PipelineStep], result: PipelineResult
    ) -> None:
        """并行执行步骤"""
        coros = [self._execute_step(step, result.context) for step in steps]
        step_results = await asyncio.gather(*coros, return_exceptions=True)

        has_failure = False
        for step, sr in zip(steps, step_results):
            if isinstance(sr, Exception):
                sr = StepResult(
                    step_name=step.name,
                    status=PipelineStatus.FAILED,
                    error=str(sr),
                )
                has_failure = True
            else:
                if sr.status == PipelineStatus.FAILED:
                    has_failure = True
                if step.output_key and sr.output:
                    result.context[step.output_key] = sr.output
            result.step_results.append(sr)

        if has_failure:
            result.status = PipelineStatus.FAILED

    # ─── 单步执行 ─────────────────────────────────────────

    async def _execute_step(
        self, step: PipelineStep, context: Dict[str, Any]
    ) -> StepResult:
        """执行单个步骤"""
        step_result = StepResult(
            step_name=step.name,
            started_at=datetime.now(),
        )
        start_time = time.monotonic()

        # 条件检查
        if step.condition:
            if not self._evaluate_condition(step.condition, context):
                step_result.status = PipelineStatus.SKIPPED
                step_result.completed_at = datetime.now()
                step_result.duration_ms = (time.monotonic() - start_time) * 1000
                logger.info("Step '%s' skipped (condition not met)", step.name)
                return step_result

        # 解析输入变量
        input_data = self._resolve_variables(step.input_data or {}, context)

        # 通知前端
        await self._notify("step_started", {"step": step.name, "capability": step.capability})

        # 重试执行
        step_result.status = PipelineStatus.RUNNING
        max_attempts = max(step.max_retries, 1)

        for attempt in range(max_attempts):
            step_result.retries = attempt
            try:
                output = await self._execute_capability(step, input_data)
                step_result.output = output if isinstance(output, dict) else {"result": output}
                step_result.status = PipelineStatus.COMPLETED
                break
            except asyncio.TimeoutError:
                timeout_seconds = self._get_timeout_seconds(step.timeout)
                step_result.error = (
                    f"Step '{step.name}' timed out after {timeout_seconds:g}s"
                    if timeout_seconds is not None
                    else f"Step '{step.name}' timed out"
                )
                if attempt >= max_attempts - 1:
                    step_result.status = PipelineStatus.FAILED
                    logger.error(
                        "Step '%s' timed out after %d attempts",
                        step.name,
                        attempt + 1,
                    )
                else:
                    input_data["_previous_error"] = step_result.error
                    logger.warning(
                        "Step '%s' attempt %d timed out, retrying",
                        step.name,
                        attempt + 1,
                    )
            except Exception as exc:
                step_result.error = str(exc)
                if attempt >= max_attempts - 1:
                    step_result.status = PipelineStatus.FAILED
                    logger.error("Step '%s' failed after %d attempts: %s", step.name, attempt + 1, exc)
                else:
                    input_data["_previous_error"] = str(exc)
                    logger.warning("Step '%s' attempt %d failed, retrying: %s", step.name, attempt + 1, exc)

        step_result.completed_at = datetime.now()
        step_result.duration_ms = (time.monotonic() - start_time) * 1000

        # 通知前端
        await self._notify(
            "step_completed",
            {
                "step": step.name,
                "status": step_result.status.value,
                "duration_ms": step_result.duration_ms,
            },
        )

        return step_result

    # ─── 变量替换 ─────────────────────────────────────────

    @staticmethod
    def _resolve_variables(data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """解析 ${variable} 引用"""
        return {
            key: Pipeline._resolve_value(value, context)
            for key, value in data.items()
        }

    @staticmethod
    def _resolve_value(value: Any, context: Dict[str, Any]) -> Any:
        """递归解析字符串、字典、列表和元组中的变量引用。"""
        if isinstance(value, str):
            return _substitute(value, context)
        if isinstance(value, dict):
            return Pipeline._resolve_variables(value, context)
        if isinstance(value, list):
            return [Pipeline._resolve_value(item, context) for item in value]
        if isinstance(value, tuple):
            return tuple(Pipeline._resolve_value(item, context) for item in value)
        return value

    @staticmethod
    def _get_timeout_seconds(timeout: Optional[float]) -> Optional[float]:
        """标准化 timeout 配置，忽略非正数和非法值。"""
        if timeout is None:
            return None
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            return None
        return timeout_value if timeout_value > 0 else None

    async def _execute_capability(
        self,
        step: PipelineStep,
        input_data: Dict[str, Any],
    ) -> Any:
        """按需为能力执行附加 asyncio.wait_for 超时控制。"""
        execution = self._capabilities.execute(step.capability, **input_data)
        timeout_seconds = self._get_timeout_seconds(step.timeout)
        if timeout_seconds is None:
            return await execution
        return await asyncio.wait_for(execution, timeout=timeout_seconds)

    # ─── 条件评估 ─────────────────────────────────────────

    @staticmethod
    def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
        """安全评估条件表达式"""
        try:
            return bool(eval(condition, {"__builtins__": {}}, context))
        except Exception:
            return False

    # ─── 配置解析 ─────────────────────────────────────────

    @staticmethod
    def _parse_config(name: str, template: Dict[str, Any]) -> PipelineConfig:
        """从 dict 解析 PipelineConfig"""
        steps = []
        for step_def in template.get("steps", []):
            # 兼容 "agent" 和 "capability" 字段
            capability = step_def.get("capability") or step_def.get("agent", "")
            steps.append(
                PipelineStep(
                    name=step_def["name"],
                    capability=capability,
                    input_data=step_def.get("input"),
                    output_key=step_def.get("output_key"),
                    condition=step_def.get("condition"),
                    max_retries=step_def.get("max_retries", step_def.get("max_iterations", 1)),
                    timeout=step_def.get("timeout"),
                )
            )

        return PipelineConfig(
            name=name,
            description=template.get("description", ""),
            mode=template.get("mode", "sequential"),
            steps=steps,
        )

    # ─── 通知 ────────────────────────────────────────────

    async def _notify(self, event_type: str, data: Dict[str, Any]) -> None:
        """通过 bus 广播状态更新给前端"""
        if not self._bus:
            return
        try:
            from ..bus.types import Event

            event = Event(source="pipeline", event_type=event_type, data=data)
            await self._bus.publish(event)
        except Exception:
            pass  # 通知失败不影响执行


# ─── 辅助函数 ─────────────────────────────────────────────


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
