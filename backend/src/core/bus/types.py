"""消息总线 - 统一数据类型定义

定义消息总线中所有消息类型、事件、请求、响应的数据结构。
支持优先级、TTL、关联追踪等完整特性。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
from enum import Enum
import uuid


class MessageType(Enum):
    """消息类型枚举"""
    EVENT = "event"
    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"


class Priority(int, Enum):
    """消息优先级（数值越大，优先级越高）"""
    LOW = 0
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


@dataclass
class Message:
    """统一消息基类

    所有消息类型的基础，包含完整的元数据字段。

    Attributes:
        id: 消息唯一标识
        type: 消息类型 (EVENT, REQUEST, RESPONSE, BROADCAST)
        source: 发送者标识
        target: 接收者标识（可选，None 表示广播或无特定目标）
        data: 消息载荷数据
        timestamp: 消息创建时间戳
        correlation_id: 关联 ID，用于追踪事件链
        reply_to: 回复地址，用于请求/响应模式
        ttl: 消息生存时间（秒），None 表示永不过期
        priority: 消息优先级，数值越大越优先
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.EVENT
    source: str = ""
    target: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reply_to: Optional[str] = None
    ttl: Optional[int] = None
    priority: int = Priority.NORMAL

    def is_expired(self) -> bool:
        """检查消息是否已过期"""
        if self.ttl is None:
            return False
        elapsed = (datetime.now() - self.timestamp).total_seconds()
        return elapsed > self.ttl


@dataclass
class Event(Message):
    """事件消息

    继承 Message，用于发布/订阅模式。
    event_type 标识事件类别，如 "code_generated"、"review_completed"。
    """
    type: MessageType = field(default=MessageType.EVENT, init=False)
    event_type: str = ""


@dataclass
class Request(Message):
    """请求消息

    继承 Message，用于请求/响应模式。
    reply_to 标识回复地址，timeout 指定等待超时。
    """
    type: MessageType = field(default=MessageType.REQUEST, init=False)
    reply_to: Optional[str] = field(default_factory=lambda: str(uuid.uuid4()))
    timeout: float = 30.0


@dataclass
class Response(Message):
    """响应消息

    继承 Message，通过 correlation_id 关联到原始请求。
    success 标识请求是否成功，error 包含错误信息。
    """
    type: MessageType = field(default=MessageType.RESPONSE, init=False)
    success: bool = True
    error: Optional[str] = None


@dataclass
class Subscription:
    """订阅信息

    Attributes:
        event_type: 订阅的事件类型
        handler: 事件处理函数
        filter_fn: 可选的过滤函数，返回 True 才处理
        priority: 订阅者优先级，影响处理顺序
    """
    event_type: str
    handler: Callable
    filter_fn: Optional[Callable[[Event], bool]] = None
    priority: int = Priority.NORMAL


@dataclass
class BusMetrics:
    """总线运行指标

    Attributes:
        messages_published: 已发布的消息总数
        messages_delivered: 已成功投递的消息数
        messages_failed: 投递失败的消息数
        requests_sent: 已发送的请求数
        requests_timed_out: 请求超时数
        broadcasts_sent: 已广播的消息数
        avg_latency_ms: 平均处理延迟（毫秒）
        total_latency_ms: 总处理延迟（毫秒），用于计算平均值
    """
    messages_published: int = 0
    messages_delivered: int = 0
    messages_failed: int = 0
    requests_sent: int = 0
    requests_timed_out: int = 0
    broadcasts_sent: int = 0
    avg_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    def record_latency(self, latency_ms: float):
        """记录一次处理延迟"""
        self.total_latency_ms += latency_ms
        total = self.messages_delivered + self.messages_failed
        if total > 0:
            self.avg_latency_ms = self.total_latency_ms / total

    def to_dict(self) -> dict[str, Any]:
        """转为字典格式"""
        return {
            "messages_published": self.messages_published,
            "messages_delivered": self.messages_delivered,
            "messages_failed": self.messages_failed,
            "requests_sent": self.requests_sent,
            "requests_timed_out": self.requests_timed_out,
            "broadcasts_sent": self.broadcasts_sent,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }
