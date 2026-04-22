"""消息总线 - 通信通道抽象

提供三种通道类型：
- EventChannel: 发布/订阅通道
- RequestChannel: 请求/响应通道
- BroadcastChannel: 广播通道
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from .types import (
    Event,
    Message,
    Request,
    Response,
    Subscription,
    Priority,
)

logger = logging.getLogger(__name__)


class EventChannel:
    """事件通道 - 发布/订阅模式

    支持：
    - 按 event_type 订阅
    - 订阅过滤（filter_fn）
    - 订阅者优先级排序
    - 取消订阅
    """

    def __init__(self):
        # event_type -> [Subscription]
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        handler: Callable,
        filter_fn: Optional[Callable[[Event], bool]] = None,
        priority: int = Priority.NORMAL,
    ) -> Subscription:
        """注册事件订阅

        Args:
            event_type: 事件类型
            handler: 处理函数 (async or sync)
            filter_fn: 可选过滤函数
            priority: 订阅者优先级

        Returns:
            创建的 Subscription 对象
        """
        sub = Subscription(
            event_type=event_type,
            handler=handler,
            filter_fn=filter_fn,
            priority=priority,
        )
        self._subscriptions[event_type].append(sub)
        # 按优先级降序排列（高优先级先处理）
        self._subscriptions[event_type].sort(
            key=lambda s: s.priority, reverse=True
        )
        logger.debug(f"Subscribed to '{event_type}', total: {len(self._subscriptions[event_type])}")
        return sub

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """取消事件订阅

        Args:
            event_type: 事件类型
            handler: 要移除的处理函数

        Returns:
            是否成功移除
        """
        subs = self._subscriptions.get(event_type, [])
        before = len(subs)
        self._subscriptions[event_type] = [
            s for s in subs if s.handler is not handler
        ]
        removed = before - len(self._subscriptions[event_type])
        if removed > 0:
            logger.debug(f"Unsubscribed from '{event_type}', removed {removed}")
        return removed > 0

    async def dispatch(self, event: Event) -> int:
        """分发事件给所有匹配的订阅者

        Args:
            event: 要分发的事件

        Returns:
            成功处理的订阅者数量
        """
        subs = self._subscriptions.get(event.event_type, [])
        delivered = 0

        for sub in subs:
            # 过滤检查
            if sub.filter_fn is not None:
                try:
                    if not sub.filter_fn(event):
                        continue
                except Exception as e:
                    logger.warning(f"Filter function error for '{event.event_type}': {e}")
                    continue

            # 调用处理函数
            try:
                if asyncio.iscoroutinefunction(sub.handler):
                    await sub.handler(event)
                else:
                    sub.handler(event)
                delivered += 1
            except Exception as e:
                logger.error(f"Handler error for '{event.event_type}': {e}")

        return delivered

    def get_subscriber_count(self, event_type: str) -> int:
        """获取指定事件类型的订阅者数量"""
        return len(self._subscriptions.get(event_type, []))

    def get_all_event_types(self) -> list[str]:
        """获取所有已注册的事件类型"""
        return list(self._subscriptions.keys())


class RequestChannel:
    """请求/响应通道

    支持：
    - 注册请求处理器（按 target 名称）
    - 发送请求并等待响应
    - 超时控制
    """

    def __init__(self):
        # target -> handler
        self._handlers: dict[str, Callable] = {}
        # reply_to -> asyncio.Future (等待响应)
        self._pending: dict[str, asyncio.Future] = {}

    def register_handler(self, target: str, handler: Callable):
        """注册请求处理器

        Args:
            target: 目标名称（如 agent 名称）
            handler: 处理函数，接收 Request 返回 Response
        """
        self._handlers[target] = handler
        logger.debug(f"Registered request handler for '{target}'")

    def unregister_handler(self, target: str) -> bool:
        """注销请求处理器"""
        if target in self._handlers:
            del self._handlers[target]
            logger.debug(f"Unregistered request handler for '{target}'")
            return True
        return False

    async def send_request(
        self,
        request: Request,
        timeout: Optional[float] = None,
    ) -> Response:
        """发送请求并等待响应

        Args:
            request: 请求消息
            timeout: 超时秒数（默认使用 request.timeout）

        Returns:
            响应消息

        Raises:
            asyncio.TimeoutError: 请求超时
            ValueError: 目标处理器未注册
        """
        target = request.target
        if target is None:
            raise ValueError("Request target cannot be None")

        handler = self._handlers.get(target)
        if handler is None:
            raise ValueError(f"No handler registered for target '{target}'")

        effective_timeout = timeout if timeout is not None else request.timeout

        # 创建 Future 等待响应
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Response] = loop.create_future()
        reply_to = request.reply_to or request.id
        self._pending[reply_to] = future

        async def _run_handler():
            """在后台运行处理器并设置 future"""
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(request)
                else:
                    result = handler(request)

                if isinstance(result, Response):
                    result.correlation_id = request.correlation_id
                    if not future.done():
                        future.set_result(result)
                elif isinstance(result, dict):
                    resp = Response(
                        source=target,
                        target=request.source,
                        data=result,
                        correlation_id=request.correlation_id,
                    )
                    if not future.done():
                        future.set_result(resp)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if not future.done():
                    future.set_exception(e)

        # 启动处理器任务（不阻塞，让 timeout 可以生效）
        handler_task = asyncio.create_task(_run_handler())

        try:
            # 等待响应（带超时）
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except asyncio.TimeoutError:
            handler_task.cancel()
            logger.warning(f"Request to '{target}' timed out after {effective_timeout}s")
            raise
        finally:
            self._pending.pop(reply_to, None)

    def resolve(self, reply_to: str, response: Response):
        """外部解析响应（用于异步处理器主动回复的场景）

        Args:
            reply_to: 原始请求的 reply_to 标识
            response: 响应消息
        """
        future = self._pending.get(reply_to)
        if future and not future.done():
            future.set_result(response)

    def has_handler(self, target: str) -> bool:
        """检查目标是否有注册处理器"""
        return target in self._handlers

    def get_pending_count(self) -> int:
        """获取等待中的请求数量"""
        return len(self._pending)


class BroadcastChannel:
    """广播通道

    支持：
    - 注册广播接收器
    - 向所有接收器广播消息
    - 按组件名称注册/注销
    """

    def __init__(self):
        # component_name -> handler
        self._receivers: dict[str, Callable] = {}

    def register(self, name: str, handler: Callable):
        """注册广播接收器

        Args:
            name: 组件名称
            handler: 处理函数
        """
        self._receivers[name] = handler
        logger.debug(f"Registered broadcast receiver '{name}'")

    def unregister(self, name: str) -> bool:
        """注销广播接收器"""
        if name in self._receivers:
            del self._receivers[name]
            logger.debug(f"Unregistered broadcast receiver '{name}'")
            return True
        return False

    async def broadcast(self, message: Message) -> int:
        """广播消息给所有接收器

        Args:
            message: 要广播的消息

        Returns:
            成功投递的接收器数量
        """
        delivered = 0
        for name, handler in self._receivers.items():
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
                delivered += 1
            except Exception as e:
                logger.error(f"Broadcast handler '{name}' error: {e}")
        return delivered

    def get_receiver_count(self) -> int:
        """获取接收器数量"""
        return len(self._receivers)

    def get_receiver_names(self) -> list[str]:
        """获取所有接收器名称"""
        return list(self._receivers.keys())
