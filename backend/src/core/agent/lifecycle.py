"""Agent 生命周期管理器

职责:
- 管理 Agent 的启动 / 停止 / 重启
- 健康检查
- 错误恢复（Agent 崩溃自动重启）
- 状态变更事件发布
"""
import asyncio
from typing import Any, Dict, Optional

from ..bus import SimpleBus, Event
from .agent import Agent, AgentStatus
from .registry import AgentRegistry


class AgentLifecycleManager:
    """Agent 生命周期管理器"""

    def __init__(
        self,
        registry: AgentRegistry,
        bus: Optional[SimpleBus] = None,
        max_restarts: int = 3,
        health_interval: float = 30.0,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._max_restarts = max_restarts
        self._health_interval = health_interval
        # 每个 Agent 的累计重启次数
        self._restart_counts: Dict[str, int] = {}
        # 健康检查后台任务句柄
        self._health_task: Optional[asyncio.Task] = None

    # ─── 单个 Agent 操作 ────────────────────────────────

    async def start_agent(self, name: str) -> bool:
        """启动指定 Agent，成功返回 True"""
        agent = self._registry.get(name)
        if agent is None:
            return False
        try:
            await agent.start()
            self._restart_counts.setdefault(name, 0)
            await self._publish_status_change(name, AgentStatus.IDLE)
            return True
        except Exception as exc:
            agent.status = AgentStatus.ERROR
            await self._publish_status_change(
                name, AgentStatus.ERROR, error=str(exc)
            )
            return False

    async def stop_agent(self, name: str) -> bool:
        """停止指定 Agent"""
        agent = self._registry.get(name)
        if agent is None:
            return False
        try:
            await agent.stop()
            await self._publish_status_change(name, AgentStatus.STOPPED)
            return True
        except Exception as exc:
            agent.status = AgentStatus.ERROR
            await self._publish_status_change(
                name, AgentStatus.ERROR, error=str(exc)
            )
            return False

    async def restart_agent(self, name: str) -> bool:
        """重启指定 Agent"""
        await self.stop_agent(name)
        return await self.start_agent(name)

    # ─── 健康检查 ────────────────────────────────────────

    async def health_check(self) -> Dict[str, AgentStatus]:
        """检查所有 Agent 的状态，返回 {name: status}"""
        result: Dict[str, AgentStatus] = {}
        for meta in self._registry.list_all():
            agent = self._registry.get(meta.name)
            if agent:
                result[meta.name] = agent.status
        return result

    async def check_and_recover(self) -> None:
        """检查所有 Agent 状态并尝试恢复处于 ERROR 的 Agent"""
        for meta in self._registry.list_all():
            agent = self._registry.get(meta.name)
            if agent is None:
                continue
            if agent.status == AgentStatus.ERROR:
                count = self._restart_counts.get(meta.name, 0)
                if count < self._max_restarts:
                    self._restart_counts[meta.name] = count + 1
                    await self.restart_agent(meta.name)

    # ─── 后台健康检查任务 ────────────────────────────────

    def start_health_monitor(self) -> None:
        """启动后台健康检查循环"""
        if self._health_task is None or self._health_task.done():
            self._health_task = asyncio.create_task(self._health_loop())

    async def stop_health_monitor(self) -> None:
        """停止后台健康检查"""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

    async def _health_loop(self) -> None:
        """循环执行健康检查与错误恢复"""
        while True:
            await asyncio.sleep(self._health_interval)
            try:
                await self.check_and_recover()
            except Exception:
                pass  # 健康检查自身的错误不应阻塞循环

    # ─── 状态变更事件 ────────────────────────────────────

    async def _publish_status_change(
        self,
        agent_name: str,
        new_status: AgentStatus,
        error: str = "",
    ) -> None:
        """发布 Agent 状态变更事件"""
        if self._bus is None:
            return
        data: Dict[str, Any] = {
            "agent_name": agent_name,
            "status": new_status.value,
        }
        if error:
            data["error"] = error
        event = Event(
            source="lifecycle_manager",
            event_type="agent_status_changed",
            data=data,
        )
        await self._bus.publish(event)
