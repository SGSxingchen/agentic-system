"""Agent 基类 - 增强版

提供:
- 能力系统 (capabilities)
- 元数据 (metadata)
- 状态管理 (AgentStatus)
- 生命周期方法 (start/stop)
- 事件处理和发射
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..bus import SimpleBus, Event


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


class BaseAgent(ABC):
    """Agent 基类 - 增强版

    包含能力系统、生命周期管理和元数据支持。
    向后兼容旧版接口：name, bus, on_event, emit, process。
    """

    def __init__(
        self,
        name: str,
        bus: SimpleBus,
        config: Optional[Dict[str, Any]] = None,
        description: str = "",
        capabilities: Optional[List[str]] = None,
    ):
        self.name = name
        self.bus = bus
        self.config = config or {}
        self._description = description
        self._capabilities: List[str] = capabilities or []
        self._status: AgentStatus = AgentStatus.STOPPED

    # ─── 状态 ─────────────────────────────────────────────

    @property
    def status(self) -> AgentStatus:
        """当前状态"""
        return self._status

    @status.setter
    def status(self, value: AgentStatus) -> None:
        self._status = value

    # ─── 生命周期 ─────────────────────────────────────────

    async def start(self) -> None:
        """启动 Agent（子类可覆盖添加初始化逻辑）"""
        self._status = AgentStatus.IDLE

    async def stop(self) -> None:
        """停止 Agent（子类可覆盖添加清理逻辑）"""
        self._status = AgentStatus.STOPPED

    # ─── 事件处理 ─────────────────────────────────────────

    async def on_event(self, event: Event) -> None:
        """响应事件（由总线调用）

        设置状态为 BUSY，处理完成后恢复 IDLE。
        处理出错时状态设为 ERROR。
        """
        self._status = AgentStatus.BUSY
        try:
            result = await self.process(event.data)
            if result:
                await self.emit(f"{self.name}_completed", result)
            self._status = AgentStatus.IDLE
        except Exception:
            self._status = AgentStatus.ERROR
            raise

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """发射事件到总线"""
        event = Event(
            source=self.name,
            event_type=event_type,
            data=data,
        )
        await self.bus.publish(event)

    # ─── 核心处理 ─────────────────────────────────────────

    @abstractmethod
    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理逻辑（子类实现）"""
        pass

    # ─── 能力与元数据 ─────────────────────────────────────

    def get_capabilities(self) -> List[str]:
        """返回该 Agent 支持的能力列表"""
        return list(self._capabilities)

    def get_metadata(self) -> AgentMetadata:
        """返回 Agent 元数据"""
        return AgentMetadata(
            name=self.name,
            description=self._description,
            capabilities=self.get_capabilities(),
            status=self._status,
        )
