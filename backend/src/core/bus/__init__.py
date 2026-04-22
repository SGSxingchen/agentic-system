"""消息总线模块

提供统一消息总线及其所有组件。
"""
from .types import (
    Message,
    Event,
    Request,
    Response,
    MessageType,
    Priority,
    BusMetrics,
    Subscription,
)
from .unified_bus import UnifiedBus
from .channels import EventChannel, RequestChannel, BroadcastChannel
from .router import MessageRouter

# 向后兼容
SimpleBus = UnifiedBus

__all__ = [
    # 数据类型
    "Message",
    "Event",
    "Request",
    "Response",
    "MessageType",
    "Priority",
    "BusMetrics",
    "Subscription",
    # 总线
    "UnifiedBus",
    "SimpleBus",
    # 通道
    "EventChannel",
    "RequestChannel",
    "BroadcastChannel",
    # 路由
    "MessageRouter",
]
