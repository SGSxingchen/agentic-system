"""集成测试：OpenAI / Anthropic 客户端接入 call_with_retry。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.openai_client import OpenAIClient


class _ConnErr(Exception):
    pass


_ConnErr.__name__ = "APIConnectionError"


@pytest.mark.asyncio
async def test_openai_chat_retries_on_connection_error(monkeypatch):
    """瞬态错误重试 3 次后成功。"""
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-3.5-turbo"
    client.generation_config = {}
    client.client = MagicMock()
    client._max_retries = 3
    client._retry_initial_delay = 0.0  # 单测加速

    fake_resp = MagicMock()
    msg = MagicMock()
    msg.content = "hi"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    fake_resp.choices = [choice]
    fake_resp.usage = None

    calls = 0

    async def fake_create(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _ConnErr("boom")
        return fake_resp

    client.client.chat.completions.create = fake_create

    out = await client.chat([{"role": "user", "content": "hi"}])
    assert out.content == "hi"
    assert calls == 3


@pytest.mark.asyncio
async def test_openai_chat_invokes_on_retry_callback():
    """on_retry 应被调用并接收 attempt 序号。"""
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-3.5-turbo"
    client.generation_config = {}
    client.client = MagicMock()
    client._max_retries = 3
    client._retry_initial_delay = 0.0

    fake_resp = MagicMock()
    msg = MagicMock()
    msg.content = "ok"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    fake_resp.choices = [choice]
    fake_resp.usage = None

    calls = 0

    async def fake_create(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 2:
            raise _ConnErr("transient")
        return fake_resp

    client.client.chat.completions.create = fake_create

    seen: list[int] = []

    def on_retry(attempt, exc, sleep_for):
        seen.append(attempt)

    out = await client.chat([{"role": "user", "content": "hi"}], on_retry=on_retry)
    assert out.content == "ok"
    assert seen == [1]


@pytest.mark.asyncio
async def test_openai_chat_stream_does_not_retry_mid_stream():
    """流式中途断开不重试，仅在建立流前重试。"""
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-3.5-turbo"
    client.generation_config = {}
    client.client = MagicMock()
    client._max_retries = 3
    client._retry_initial_delay = 0.0

    open_stream_calls = 0

    class _BrokenStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            # 第一次 yield 一个 chunk 后断开
            raise _ConnErr("mid-stream connection drop")

    async def fake_create(**kwargs):
        nonlocal open_stream_calls
        open_stream_calls += 1
        return _BrokenStream()

    client.client.chat.completions.create = fake_create

    events = []
    with pytest.raises(_ConnErr):
        async for ev in client.chat_stream([{"role": "user", "content": "hi"}]):
            events.append(ev)

    # 建立流只有一次（spec §R2: 中途断开不重试）
    assert open_stream_calls == 1
