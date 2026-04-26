"""LLM 工厂"""
from typing import Any, Dict, Optional
from .base import BaseLLMClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient


def create_llm_client(
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
    generation_config: Optional[Dict[str, Any]] = None,
) -> BaseLLMClient:
    """创建 LLM 客户端"""
    if provider == "openai":
        return OpenAIClient(api_key, model, base_url, generation_config)
    elif provider == "anthropic":
        return AnthropicClient(api_key, model, base_url, generation_config)
    else:
        raise ValueError(f"不支持的 provider: {provider}")
