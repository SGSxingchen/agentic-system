"""统一消息总线 - UnifiedBus

整合 EventChannel、RequestChannel、BroadcastChannel 和 MessageRouter，
提供统一的消息通信接口。

支持:
- 发布/订阅 (事件驱动)
- 请求/响应 (同步调用)
- 点对点消息
- 广播
- 优先级队列
- 消息历史
- 运行指标统计
- 向后兼容 SimpleBus 接口
"""
import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, Optional

from .types import (
    Event,
    Message,
    MessageType,
    Request,
    Response,
    BusMetrics,
    Priority,
)
from .channels import EventChannel, RequestChannel, BroadcastChannel
from .router import MessageRouter

logger = logging.getLogger(__name__)


class UnifiedBus:
    """统一消息总线

    所有组件通过总线通信，支持多种通信模式。

    Usage::

        bus = UnifiedBus()
        await bus.start()

        # 发布/订阅
        bus.subscribe("code_generated", my_handler)
        await bus.publish(Event(source="coder", event_type="code_generated", data={...}))

        # 请求/响应
        bus.handle_request("reviewer", review_handler)
        response = await bus.request("reviewer", Request(data={"code": "..."}))

        # 广播
        bus.register_broadcast_receiver("monitor", monitor_handler)
        await bus.broadcast(Message(data={"status": "ok"}))

        await bus.stop()
    """

    def __init__(self, queue_size: int = 10000, history_size: int = 100):
        # 通信通道
        self._event_channel = EventChannel()
        self._request_channel = RequestChannel()
        self._broadcast_channel = BroadcastChannel()
        self._router = MessageRouter()

        # 优先级队列: (-priority, counter, message)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(
            maxsize=queue_size
        )
        self._counter = 0  # 保证同优先级 FIFO

        # 消息历史
        self._history: deque[Message] = deque(maxlen=history_size)

        # 运行指标
        self._metrics = BusMetrics()

        # 运行状态
        self._running = False
        self._process_task: Optional[asyncio.Task] = None

        # 向后兼容 SimpleBus: 旧代码可能访问 bus._subscribers
        self._subscribers: dict[str, list[Callable]] = {}

    # ─── 生命周期 ─────────────────────────────────────────

    async def start(self):
        """启动总线消息处理循环"""
        if self._running:
            return
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.info("UnifiedBus started")

    async def stop(self):
        """停止总线"""
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None
        logger.info("UnifiedBus stopped")

    # ─── 发布/订阅 ───────────────────────────────────────

    async def publish(self, event: Event):
        """发布事件到总线

        事件进入优先级队列，由处理循环分发给订阅者。
        """
        if event.is_expired():
            logger.debug(f"Event {event.id} expired, discarding")
            return

        self._counter += 1
        await self._queue.put((-event.priority, self._counter, event))
        self._metrics.messages_published += 1

    def subscribe(
        self,
        event_type: str,
        handler: Callable,
        filter_fn: Optional[Callable[[Event], bool]] = None,
    ):
        """订阅事件类型

        Args:
            event_type: 事件类型
            handler: 处理函数 (async or sync)
            filter_fn: 可选过滤函数
        """
        self._event_channel.subscribe(event_type, handler, filter_fn)
        # 向后兼容: 同步更新 _subscribers
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """取消订阅"""
        result = self._event_channel.unsubscribe(event_type, handler)
        # 向后兼容
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h is not handler
            ]
        return result

    # ─── 请求/响应 ───────────────────────────────────────

    async def request(
        self,
        target: str,
        message: Optional[Request] = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> Response:
        """发送请求并等待响应

        Args:
            target: 目标处理器名称
            message: 请求消息（如果为 None，从 kwargs 构建）
            timeout: 超时秒数

        Returns:
            Response 消息

        Raises:
            asyncio.TimeoutError: 请求超时
            ValueError: 目标未注册
        """
        if message is None:
            message = Request(target=target, data=kwargs, timeout=timeout)
        else:
            message.target = target
            message.timeout = timeout

        self._metrics.requests_sent += 1

        try:
            response = await self._request_channel.send_request(
                message, timeout=timeout
            )
            self._history.append(message)
            self._history.append(response)
            return response
        except asyncio.TimeoutError:
            self._metrics.requests_timed_out += 1
            raise

    def handle_request(self, target: str, handler: Callable):
        """注册请求处理器

        Args:
            target: 目标名称
            handler: 处理函数，接收 Request 返回 Response 或 dict
        """
        self._request_channel.register_handler(target, handler)

    # ─── 点对点 ──────────────────────────────────────────

    async def send(self, target: str, message: Message):
        """发送点对点消息

        通过路由器查找目标处理器并发送。
        """
        message.target = target
        delivered = await self._router.route(message)
        if delivered > 0:
            self._metrics.messages_delivered += delivered
            self._history.append(message)
        else:
            logger.warning(f"No route found for target '{target}'")

    def register_route(self, pattern: str, handler: Callable):
        """注册点对点路由

        Args:
            pattern: 路由模式 (支持 * 和 # 通配符)
            handler: 处理函数
        """
        self._router.add_route(pattern, handler)

    # ─── 广播 ────────────────────────────────────────────

    async def broadcast(self, message: Message):
        """广播消息给所有注册的接收器"""
        message.type = MessageType.BROADCAST
        delivered = await self._broadcast_channel.broadcast(message)
        self._metrics.broadcasts_sent += 1
        self._metrics.messages_delivered += delivered
        self._history.append(message)

    def register_broadcast_receiver(self, name: str, handler: Callable):
        """注册广播接收器"""
        self._broadcast_channel.register(name, handler)

    def unregister_broadcast_receiver(self, name: str) -> bool:
        """注销广播接收器"""
        return self._broadcast_channel.unregister(name)

    # ─── 消息历史 ────────────────────────────────────────

    def get_history(self, limit: int = 50) -> list[Message]:
        """获取最近的消息历史

        Args:
            limit: 返回数量上限

        Returns:
            最近的消息列表（最新在前）
        """
        items = list(self._history)
        items.reverse()
        return items[:limit]

    # ─── 统计指标 ────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取总线运行指标"""
        return {
            **self._metrics.to_dict(),
            "queue_size": self._queue.qsize(),
            "running": self._running,
            "history_size": len(self._history),
            "event_types": self._event_channel.get_all_event_types(),
            "broadcast_receivers": self._broadcast_channel.get_receiver_count(),
            "routes": self._router.get_routes(),
        }

    # ─── 内部处理循环 ────────────────────────────────────

    async def _process_loop(self):
        """从优先级队列取消息并分发"""
        while self._running:
            try:
                # 带超时取消息，允许定期检查 _running
                neg_priority, counter, message = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            start_time = time.monotonic()
            try:
                await self._dispatch(message)
            except Exception as e:
                logger.error(f"Dispatch error: {e}")
                self._metrics.messages_failed += 1
            finally:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self._metrics.record_latency(elapsed_ms)

    async def _dispatch(self, message: Message):
        """分发消息到对应通道"""
        # 检查 TTL
        if message.is_expired():
            logger.debug(f"Message {message.id} expired, discarding")
            return

        # 记录到历史
        self._history.append(message)

        if isinstance(message, Event):
            delivered = await self._event_channel.dispatch(message)
            self._metrics.messages_delivered += delivered
            if delivered == 0:
                logger.debug(
                    f"No subscribers for event '{message.event_type}'"
                )
        elif message.type == MessageType.BROADCAST:
            delivered = await self._broadcast_channel.broadcast(message)
            self._metrics.messages_delivered += delivered
        elif message.target:
            # 点对点: 尝试路由
            delivered = await self._router.route(message)
            self._metrics.messages_delivered += delivered
