"""消息总线 - 消息路由器

根据 message.target 将消息路由到正确的处理器。
支持：
- 精确匹配路由
- 通配符匹配（* 匹配单级，# 匹配多级）
- 路由表管理
"""
import asyncio
import fnmatch
import logging
import re
from collections import defaultdict
from typing import Any, Callable, Optional

from .types import Message

logger = logging.getLogger(__name__)


class MessageRouter:
    """消息路由器

    支持基于 target 路径的路由，路径用点分隔。
    示例路径:
    - "agent.coder" 精确匹配
    - "agent.*" 匹配 agent 下的任意单级（如 agent.coder, agent.reviewer）
    - "agent.#" 匹配 agent 下的任意多级（如 agent.coder, agent.coder.task1）
    """

    def __init__(self):
        # pattern -> [handlers]
        self._routes: dict[str, list[Callable]] = defaultdict(list)
        # 缓存编译好的正则（精确匹配路由不需要正则）
        self._pattern_cache: dict[str, re.Pattern] = {}

    def add_route(self, pattern: str, handler: Callable):
        """添加路由规则

        Args:
            pattern: 路由模式，支持 * (单级通配) 和 # (多级通配)
            handler: 处理函数
        """
        self._routes[pattern].append(handler)
        # 如果包含通配符，预编译正则
        if "*" in pattern or "#" in pattern:
            regex = self._pattern_to_regex(pattern)
            self._pattern_cache[pattern] = re.compile(regex)
        logger.debug(f"Added route: '{pattern}'")

    def remove_route(self, pattern: str, handler: Optional[Callable] = None) -> bool:
        """移除路由规则

        Args:
            pattern: 路由模式
            handler: 要移除的具体处理器，为 None 则移除该模式的所有处理器

        Returns:
            是否成功移除
        """
        if pattern not in self._routes:
            return False

        if handler is None:
            del self._routes[pattern]
            self._pattern_cache.pop(pattern, None)
            logger.debug(f"Removed all routes for '{pattern}'")
            return True

        before = len(self._routes[pattern])
        self._routes[pattern] = [
            h for h in self._routes[pattern] if h is not handler
        ]
        removed = before - len(self._routes[pattern])

        if not self._routes[pattern]:
            del self._routes[pattern]
            self._pattern_cache.pop(pattern, None)

        return removed > 0

    async def route(self, message: Message) -> int:
        """路由消息到匹配的处理器

        Args:
            message: 要路由的消息

        Returns:
            成功匹配并处理的处理器数量
        """
        target = message.target
        if target is None:
            return 0

        handlers = self._find_handlers(target)
        delivered = 0

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
                delivered += 1
            except Exception as e:
                logger.error(f"Route handler error for target '{target}': {e}")

        return delivered

    def _find_handlers(self, target: str) -> list[Callable]:
        """查找匹配目标的所有处理器

        Args:
            target: 目标路径

        Returns:
            匹配的处理器列表
        """
        handlers: list[Callable] = []

        for pattern, pattern_handlers in self._routes.items():
            if self._matches(pattern, target):
                handlers.extend(pattern_handlers)

        return handlers

    def _matches(self, pattern: str, target: str) -> bool:
        """检查目标是否匹配路由模式

        Args:
            pattern: 路由模式
            target: 目标路径

        Returns:
            是否匹配
        """
        # 精确匹配（无通配符）
        if "*" not in pattern and "#" not in pattern:
            return pattern == target

        # 通配符匹配
        compiled = self._pattern_cache.get(pattern)
        if compiled is None:
            regex = self._pattern_to_regex(pattern)
            compiled = re.compile(regex)
            self._pattern_cache[pattern] = compiled

        return bool(compiled.fullmatch(target))

    @staticmethod
    def _pattern_to_regex(pattern: str) -> str:
        """将路由模式转换为正则表达式

        规则:
        - * 匹配单级（不含点号的任意字符）
        - # 匹配多级（含点号的任意字符）
        - 其他字符转义

        Args:
            pattern: 路由模式

        Returns:
            正则表达式字符串
        """
        parts = pattern.split(".")
        regex_parts = []

        for part in parts:
            if part == "*":
                regex_parts.append(r"[^.]+")
            elif part == "#":
                regex_parts.append(r".*")
            else:
                regex_parts.append(re.escape(part))

        return r"\.".join(regex_parts)

    def has_route(self, target: str) -> bool:
        """检查目标是否有匹配的路由"""
        for pattern in self._routes:
            if self._matches(pattern, target):
                return True
        return False

    def get_routes(self) -> dict[str, int]:
        """获取路由表摘要（模式 -> 处理器数量）"""
        return {pattern: len(handlers) for pattern, handlers in self._routes.items()}

    def clear(self):
        """清空路由表"""
        self._routes.clear()
        self._pattern_cache.clear()
        logger.debug("Router cleared")
