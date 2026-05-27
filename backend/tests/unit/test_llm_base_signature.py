"""A6: BaseLLMClient.chat / chat_stream 应支持 on_retry 回调。"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.base import BaseLLMClient


def test_chat_signature_has_on_retry():
    sig = inspect.signature(BaseLLMClient.chat)
    assert "on_retry" in sig.parameters


def test_chat_stream_signature_has_on_retry():
    sig = inspect.signature(BaseLLMClient.chat_stream)
    assert "on_retry" in sig.parameters
