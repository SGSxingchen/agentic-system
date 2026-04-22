"""Embedding 工具 - 将文本转为向量表示

支持:
- OpenAI text-embedding-3-small
- 未来可扩展其他 embedding 提供商
"""
from typing import Optional


class EmbeddingClient:
    """Embedding 客户端"""

    def __init__(
        self,
        provider: str = "openai",
        api_key: str = "",
        model: str = "text-embedding-3-small",
        base_url: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            if self.provider == "openai":
                from openai import AsyncOpenAI
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = AsyncOpenAI(**kwargs)
            else:
                raise ValueError(f"不支持的 embedding 提供商: {self.provider}")
        return self._client

    async def embed(self, text: str) -> list[float]:
        """生成单条文本的 embedding"""
        client = self._get_client()

        if self.provider == "openai":
            response = await client.embeddings.create(
                model=self.model,
                input=text,
            )
            return response.data[0].embedding
        else:
            raise ValueError(f"不支持的 embedding 提供商: {self.provider}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成 embedding"""
        client = self._get_client()

        if self.provider == "openai":
            response = await client.embeddings.create(
                model=self.model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        else:
            raise ValueError(f"不支持的 embedding 提供商: {self.provider}")


def create_embedding_fn(
    provider: str = "openai",
    api_key: str = "",
    model: str = "text-embedding-3-small",
    base_url: Optional[str] = None,
):
    """创建 embedding 函数（返回一个 async callable）

    用法:
        embed = create_embedding_fn(api_key="sk-...")
        vector = await embed("Hello world")
    """
    client = EmbeddingClient(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    return client.embed
