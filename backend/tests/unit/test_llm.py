"""LLM 客户端单元测试

测试 LLM 工厂和客户端（使用 mock）。
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from core.llm.base import BaseLLMClient
from core.llm.factory import create_llm_client


# =====================
# 工厂测试
# =====================

class TestLLMFactory:

    @patch("core.llm.factory.OpenAIClient")
    def test_create_openai_client(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=BaseLLMClient)
        client = create_llm_client("openai", "sk-test", "gpt-4")
        mock_cls.assert_called_once_with("sk-test", "gpt-4", None)

    @patch("core.llm.factory.OpenAIClient")
    def test_create_openai_client_with_base_url(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=BaseLLMClient)
        client = create_llm_client("openai", "sk-test", "gpt-4", "http://custom/v1")
        mock_cls.assert_called_once_with("sk-test", "gpt-4", "http://custom/v1")

    @patch("core.llm.factory.AnthropicClient")
    def test_create_anthropic_client(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=BaseLLMClient)
        client = create_llm_client("anthropic", "sk-ant-test", "claude-3-opus")
        mock_cls.assert_called_once_with("sk-ant-test", "claude-3-opus", None)

    def test_create_unknown_provider(self):
        with pytest.raises(ValueError, match="不支持的 provider"):
            create_llm_client("unknown_provider", "key", "model")

    def test_create_empty_provider(self):
        with pytest.raises(ValueError):
            create_llm_client("", "key", "model")


# =====================
# BaseLLMClient 接口测试
# =====================

class TestBaseLLMClient:

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseLLMClient()

    def test_mock_client_works(self):
        mock = AsyncMock(spec=BaseLLMClient)
        mock.chat = AsyncMock(return_value="hello")
        assert mock.chat is not None

    async def test_mock_client_chat(self):
        mock = AsyncMock(spec=BaseLLMClient)
        mock.chat = AsyncMock(return_value="测试回复")
        result = await mock.chat([{"role": "user", "content": "你好"}])
        assert result == "测试回复"


# =====================
# OpenAI Client 测试 (mock openai SDK)
# =====================

class TestOpenAIClient:

    @patch("openai.AsyncOpenAI")
    def test_init_basic(self, mock_openai_cls):
        from core.llm.openai_client import OpenAIClient
        client = OpenAIClient("sk-test", "gpt-4")
        mock_openai_cls.assert_called_once_with(api_key="sk-test")
        assert client.model == "gpt-4"

    @patch("openai.AsyncOpenAI")
    def test_init_with_base_url(self, mock_openai_cls):
        from core.llm.openai_client import OpenAIClient
        client = OpenAIClient("sk-test", "gpt-4", base_url="http://proxy/v1")
        mock_openai_cls.assert_called_once_with(api_key="sk-test", base_url="http://proxy/v1")

    @patch("openai.AsyncOpenAI")
    async def test_chat_calls_api(self, mock_openai_cls):
        from core.llm.openai_client import OpenAIClient

        # 构造 mock 响应
        mock_message = MagicMock()
        mock_message.content = "AI 回复"
        mock_message.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient("sk-test", "gpt-4")
        result = await client.chat([{"role": "user", "content": "你好"}])

        assert result.content == "AI 回复"
        assert result.stop_reason == "end_turn"
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-4",
            messages=[{"role": "user", "content": "你好"}],
        )

    @patch("openai.AsyncOpenAI")
    async def test_chat_multi_turn(self, mock_openai_cls):
        from core.llm.openai_client import OpenAIClient

        mock_message = MagicMock()
        mock_message.content = "多轮回复"
        mock_message.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        client = OpenAIClient("sk-test", "gpt-4")
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
            {"role": "user", "content": "再见"},
        ]
        result = await client.chat(messages)
        assert result.content == "多轮回复"
