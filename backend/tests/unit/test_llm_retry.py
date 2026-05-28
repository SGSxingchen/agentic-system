"""单测：core.llm.retry.call_with_retry."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.retry import call_with_retry, _is_retryable


class _FakeAPIError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status={status_code}")
        self.status_code = status_code


class _FakeRateLimit(Exception):
    pass


# 给 _is_retryable 用的伪类型名匹配
_FakeRateLimit.__name__ = "RateLimitError"


@pytest.mark.asyncio
async def test_returns_on_first_success():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "ok"

    out = await call_with_retry(fn, max_retries=3, initial_delay=0.0)
    assert out == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_retries_on_connection_error():
    class _ConnErr(Exception):
        pass
    _ConnErr.__name__ = "APIConnectionError"

    attempts = 0
    seen = []

    async def fn():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _ConnErr("boom")
        return "ok"

    def on_retry(att, exc, sleep):
        seen.append((att, type(exc).__name__))

    out = await call_with_retry(fn, max_retries=3, initial_delay=0.0, on_retry=on_retry)
    assert out == "ok"
    assert attempts == 3
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_does_not_retry_on_4xx():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise _FakeAPIError(400)

    with pytest.raises(_FakeAPIError):
        await call_with_retry(fn, max_retries=3, initial_delay=0.0)
    assert calls == 1


@pytest.mark.asyncio
async def test_exhausts_and_raises():
    calls = 0
    seen: list = []

    async def fn():
        nonlocal calls
        calls += 1
        raise _FakeRateLimit("slow down")

    with pytest.raises(_FakeRateLimit):
        await call_with_retry(
            fn, max_retries=3, initial_delay=0.0,
            on_retry=lambda a, e, s: seen.append(a),
        )
    assert calls == 4  # 首发 + 3 次重试
    assert seen == [1, 2, 3]


@pytest.mark.asyncio
async def test_jitter_within_20_percent(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("core.llm.retry.random.random", lambda: 0.5)  # 中点 → 1.0x

    class _Conn(Exception):
        pass
    _Conn.__name__ = "APIConnectionError"

    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _Conn("x")
        return "ok"

    await call_with_retry(fn, max_retries=3, initial_delay=1.0)
    # delay 序列：1.0 → 2.0；jitter=0.8+0.4*0.5=1.0 → 不偏移
    assert sleeps == [1.0, 2.0]


def test_is_retryable_5xx():
    err = _FakeAPIError(503)
    assert _is_retryable(err)


def test_is_retryable_4xx_false():
    err = _FakeAPIError(400)
    assert not _is_retryable(err)


def test_is_retryable_unknown_false():
    assert not _is_retryable(ValueError("nope"))
