"""最简单的消息总线实现"""
import asyncio
from typing import Callable, Dict, List
from .types import Event, Message


class SimpleBus:
    """简单消息总线 - 最小实现"""

    def __init__(self):
        # 事件订阅表: event_type -> [handlers]
        self._subscribers: Dict[str, List[Callable]] = {}
        # 消息队列
        self._queue: asyncio.Queue = asyncio.Queue()
        # 运行标志
        self._running = False

    async def start(self):
        """启动总线"""
        self._running = True
        asyncio.create_task(self._process_loop())

    async def stop(self):
        """停止总线"""
        self._running = False

    async def publish(self, event: Event):
        """发布事件"""
        await self._queue.put(event)

    def subscribe(self, event_type: str, handler: Callable):
        """订阅事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def _process_loop(self):
        """处理消息循环"""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue

    async def _dispatch(self, event: Event):
        """分发事件"""
        handlers = self._subscribers.get(event.event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                print(f"Error in handler: {e}")
