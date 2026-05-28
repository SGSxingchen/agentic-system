"""LLM 调用重试 helper。

捕获瞬态错误（APIConnectionError / APITimeoutError / RateLimitError /
5xx APIError），指数退避 + ±20% jitter 重试。其他错误（4xx 非 429、
auth、bad-request）直接 raise，不重试。

延迟 import 避免单测时 anthropic / openai 缺失。
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional


def _is_retryable(exc: BaseException) -> bool:
    """根据异常类型名 + status_code 判断是否瞬态可重试。"""
    name = type(exc).__name__
    if name in ("APIConnectionError", "APITimeoutError", "RateLimitError"):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and 500 <= status < 600:
        return True
    return False


async def call_with_retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> Any:
    """指数退避调用 ``fn``。

    Args:
        fn: 无参 async callable。
        max_retries: 不含首发的最大重试次数。
        initial_delay: 首次退避秒数；之后 ×2 + ±20% jitter。
        on_retry: 每次重试前的同步回调 ``(attempt, exc, sleep_for)``。
                  attempt 从 1 开始计数。

    Returns:
        ``fn`` 的返回值。

    Raises:
        最后一次尝试的原异常（不重试时立即抛）。
    """
    delay = initial_delay
    attempt = 0
    while True:
        try:
            return await fn()
        except BaseException as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            jitter = delay * (0.8 + 0.4 * random.random())  # ±20%
            if on_retry is not None:
                try:
                    on_retry(attempt + 1, exc, jitter)
                except Exception:  # pragma: no cover — 回调异常不影响主流程
                    pass
            await asyncio.sleep(jitter)
            attempt += 1
            delay *= 2
