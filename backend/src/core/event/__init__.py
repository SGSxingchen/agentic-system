"""事件引擎与扳机系统

导出:
- Trigger           — 扳机数据类
- TriggerRegistry   — 扳机注册表
- EventEngine       — 事件引擎
"""
from .trigger import Trigger
from .registry import TriggerRegistry
from .engine import EventEngine

__all__ = [
    "Trigger",
    "TriggerRegistry",
    "EventEngine",
]
