"""LLM 工厂"""
from typing import Optional
from .base import BaseLLMClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient


def create_llm_client(provider: str, api_key: str, model: str, base_url: Optional[str] = None) -> BaseLLMClient:
    """创建 LLM 客户端"""
    if provider == "openai":
        return OpenAIClient(api_key, model, base_url)
    elif provider == "anthropic":
        return AnthropicClient(api_key, model, base_url)
    else:
        raise ValueError(f"不支持的 provider: {provider}")
