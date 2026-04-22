"""事件引擎 - 事件驱动的 Agent 调度核心

EventEngine 监听总线上的事件，通过扳机注册表查找匹配的扳机，
评估条件过滤，然后调度对应的 Agent 处理事件。
支持异步/同步执行模式和事件链追踪。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..bus import SimpleBus, Event
from ..agent.base import BaseAgent
from ..agent.registry import AgentRegistry
from .trigger import Trigger
from .registry import TriggerRegistry

logger = logging.getLogger(__name__)


class EventEngine:
    """事件引擎 - 将事件路由到正确的 Agent

    职责:
    - 订阅总线上的事件
    - 通过扳机注册表匹配事件 → Agent
    - 安全地评估条件表达式
    - 按优先级调度 Agent 处理
    - 支持异步并发和同步串行模式
    - 事件链追踪（correlation_id 传递）
    - 单个扳机失败不影响其他扳机
    """

    def __init__(
        self,
        bus: SimpleBus,
        agent_registry: AgentRegistry,
        trigger_registry: TriggerRegistry,
    ) -> None:
        self._bus = bus
        self._agent_registry = agent_registry
        self._trigger_registry = trigger_registry
        self._running = False
        # 已处理事件计数
        self._events_processed: int = 0
        self._events_failed: int = 0
        # 事件处理历史（用于事件链追踪）
        self._event_history: List[Dict[str, Any]] = []

    # ─── 生命周期 ─────────────────────────────────────────

    async def start(self) -> None:
        """启动事件引擎，开始监听总线事件"""
        self._running = True
        logger.info("EventEngine started")

    async def stop(self) -> None:
        """停止事件引擎"""
        self._running = False
        logger.info("EventEngine stopped")

    # ─── 核心处理 ─────────────────────────────────────────

    async def handle_event(self, event: Event) -> List[Dict[str, Any]]:
        """处理事件：匹配扳机 → 评估条件 → 调度 Agent

        Args:
            event: 待处理的事件

        Returns:
            每个扳机执行的结果列表，包含成功/失败信息
        """
        if not self._running:
            logger.warning("EventEngine is not running, ignoring event: %s", event.event_type)
            return []

        # 1. 查找匹配的扳机（已按优先级排序）
        triggers = self._trigger_registry.get_triggers_for_event(event.event_type)
        if not triggers:
            return []

        # 2. 条件过滤
        valid_triggers = []
        for trigger in triggers:
            if self._evaluate_condition(trigger, event):
                valid_triggers.append(trigger)

        if not valid_triggers:
            return []

        # 3. 分组：同步扳机串行执行，异步扳机并发执行
        sync_triggers = [t for t in valid_triggers if not t.async_mode]
        async_triggers = [t for t in valid_triggers if t.async_mode]

        results: List[Dict[str, Any]] = []

        # 先串行执行同步扳机
        for trigger in sync_triggers:
            result = await self._execute_trigger(trigger, event)
            results.append(result)

        # 再并发执行异步扳机
        if async_triggers:
            tasks = [
                self._execute_trigger(trigger, event)
                for trigger in async_triggers
            ]
            async_results = await asyncio.gather(*tasks, return_exceptions=False)
            results.extend(async_results)

        self._events_processed += 1
        return results

    # ─── 扳机执行 ─────────────────────────────────────────

    async def _execute_trigger(
        self, trigger: Trigger, event: Event
    ) -> Dict[str, Any]:
        """执行单个扳机，调度对应 Agent

        单个扳机失败不影响其他扳机的执行。

        Returns:
            执行结果字典，包含 trigger_id, agent_name, success, result/error
        """
        result: Dict[str, Any] = {
            "trigger_id": trigger.id,
            "agent_name": trigger.agent_name,
            "event_type": event.event_type,
            "correlation_id": event.correlation_id,
        }

        try:
            # 查找目标 Agent
            agent = self._agent_registry.get(trigger.agent_name)
            if agent is None:
                result["success"] = False
                result["error"] = f"Agent '{trigger.agent_name}' not found in registry"
                self._events_failed += 1
                logger.warning(
                    "Trigger %s: Agent '%s' not found",
                    trigger.id,
                    trigger.agent_name,
                )
                return result

            # 调用 Agent 处理事件
            # 优先使用 on_event（完整事件处理），否则回退到 process（纯数据处理）
            if hasattr(agent, "on_event"):
                await agent.on_event(event)
                result["success"] = True
                result["result"] = "on_event completed"
            else:
                process_result = await agent.process(event.data)
                result["success"] = True
                result["result"] = process_result

            logger.debug(
                "Trigger %s: Agent '%s' handled event '%s' successfully",
                trigger.id,
                trigger.agent_name,
                event.event_type,
            )

        except Exception as exc:
            result["success"] = False
            result["error"] = str(exc)
            self._events_failed += 1
            logger.error(
                "Trigger %s: Agent '%s' failed on event '%s': %s",
                trigger.id,
                trigger.agent_name,
                event.event_type,
                exc,
            )

        # 记录到事件历史
        self._event_history.append(result)

        return result

    # ─── 条件评估 ─────────────────────────────────────────

    @staticmethod
    def _evaluate_condition(trigger: Trigger, event: Event) -> bool:
        """安全地评估扳机条件表达式

        条件表达式中可引用事件 data 中的字段作为局部变量。
        例如: condition="language == 'python'" 会在 event.data 中查找 language。

        无条件或条件为空时返回 True。
        评估失败时返回 False（安全降级）。
        """
        if not trigger.condition:
            return True

        try:
            # 构建安全的局部变量：仅包含事件数据
            local_vars = dict(event.data) if event.data else {}
            # 添加事件自身属性
            local_vars["event_type"] = event.event_type
            local_vars["source"] = event.source

            # 受限求值：不提供 __builtins__ 以限制可用函数
            result = eval(trigger.condition, {"__builtins__": {}}, local_vars)
            return bool(result)
        except Exception as exc:
            logger.warning(
                "Trigger %s: condition '%s' evaluation failed: %s",
                trigger.id,
                trigger.condition,
                exc,
            )
            return False

    # ─── 总线订阅 ─────────────────────────────────────────

    def subscribe_all(self) -> None:
        """为 TriggerRegistry 中所有已注册扳机的事件类型订阅总线"""
        seen_types: set = set()
        for trigger in self._trigger_registry.list_all():
            if trigger.event_type not in seen_types:
                self._bus.subscribe(trigger.event_type, self.handle_event)
                seen_types.add(trigger.event_type)

    def subscribe(self, event_type: str) -> None:
        """手动订阅某个事件类型"""
        self._bus.subscribe(event_type, self.handle_event)

    # ─── 事件链追踪 ──────────────────────────────────────

    def get_event_chain(self, correlation_id: str) -> List[Dict[str, Any]]:
        """根据 correlation_id 获取事件链中的所有执行结果

        注意: 需要调用 handle_event 后才会记录结果。
        结果基于 _execute_trigger 返回的 result，其中包含 correlation_id。
        """
        return [
            record
            for record in self._event_history
            if record.get("correlation_id") == correlation_id
        ]

    def get_history(self) -> List[Dict[str, Any]]:
        """获取所有事件处理历史"""
        return list(self._event_history)

    # ─── 统计信息 ─────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """返回引擎统计信息"""
        return {
            "running": self._running,
            "events_processed": self._events_processed,
            "events_failed": self._events_failed,
            "total_triggers": len(self._trigger_registry),
        }
