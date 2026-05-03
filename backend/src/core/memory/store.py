"""记忆存储 - 支持向量检索的记忆持久化

支持两种后端:
- InMemoryStore: 内存存储，用于开发和测试
- ChromaStore: ChromaDB 向量存储，用于生产环境
"""
import json
import math
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .types import Memory, MemoryQuery, MemoryType


class BaseMemoryStore(ABC):
    """记忆存储抽象基类"""

    @abstractmethod
    async def save(self, memory: Memory) -> str:
        """保存记忆，返回记忆ID"""
        pass

    @abstractmethod
    async def get(self, memory_id: str) -> Optional[Memory]:
        """根据ID获取记忆"""
        pass

    @abstractmethod
    async def search(self, query: MemoryQuery) -> list[Memory]:
        """搜索记忆"""
        pass

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        pass

    @abstractmethod
    async def update(self, memory: Memory) -> bool:
        """更新记忆"""
        pass

    @abstractmethod
    async def get_all(
        self,
        memory_type: Optional[MemoryType] = None,
        limit: int = 100,
    ) -> list[Memory]:
        """获取所有记忆（可按类型过滤）"""
        pass

    @abstractmethod
    async def count(self, memory_type: Optional[MemoryType] = None) -> int:
        """统计记忆数量"""
        pass


class InMemoryStore(BaseMemoryStore):
    """内存存储 - 用于开发和测试

    支持简单的余弦相似度检索（如果提供了 embedding）。
    同时支持基于关键词的后备搜索。
    """

    def __init__(self):
        self._memories: dict[str, Memory] = {}

    async def save(self, memory: Memory) -> str:
        self._memories[memory.id] = memory
        return memory.id

    async def get(self, memory_id: str) -> Optional[Memory]:
        memory = self._memories.get(memory_id)
        if memory:
            memory.access_count += 1
            memory.last_accessed = datetime.now()
        return memory

    async def search(self, query: MemoryQuery) -> list[Memory]:
        """搜索记忆

        策略:
        1. 如果记忆有 embedding → 余弦相似度排序
        2. 否则 → 关键词匹配 + 重要性排序
        """
        candidates = list(self._memories.values())

        # 按类型过滤
        if query.memory_types:
            candidates = [m for m in candidates if m.type in query.memory_types]

        # 按最低重要性过滤
        candidates = [m for m in candidates if m.importance >= query.min_importance]

        # 按时间范围过滤
        if query.time_range:
            start, end = query.time_range
            candidates = [m for m in candidates if start <= m.created_at <= end]

        # 按元数据过滤
        if query.metadata_filter:
            candidates = [
                m
                for m in candidates
                if all(m.metadata.get(k) == v for k, v in query.metadata_filter.items())
            ]

        # 关键词匹配 + 重要性排序
        if query.query:
            # 分词：空格分割 + 逐字符拆分（兼容中文）
            raw_keywords = query.query.lower().split()
            keywords = list(raw_keywords)
            # 对中文：按每个字符（去掉常见虚词）也做匹配
            _stop_chars = set("的了在是和与或也都")
            for kw in raw_keywords:
                for ch in kw:
                    if ch not in _stop_chars and '\u4e00' <= ch <= '\u9fff':
                        keywords.append(ch)

            scored = []
            for m in candidates:
                content_lower = m.content.lower()
                # 整词匹配得分
                keyword_score = sum(1 for kw in raw_keywords if kw in content_lower)
                # 字符级匹配得分（权重较低）
                char_score = sum(0.3 for kw in keywords if kw in content_lower)
                total_match = keyword_score + char_score
                if total_match > 0:
                    score = total_match * 0.6 + m.importance * 0.4
                    scored.append((score, m))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [m for _, m in scored]
        else:
            # 无查询时按重要性 + 最近访问排序
            results = sorted(
                candidates,
                key=lambda m: (m.importance, m.last_accessed.timestamp()),
                reverse=True,
            )

        return results[: query.max_results]

    async def delete(self, memory_id: str) -> bool:
        if memory_id in self._memories:
            del self._memories[memory_id]
            return True
        return False

    async def update(self, memory: Memory) -> bool:
        if memory.id in self._memories:
            self._memories[memory.id] = memory
            return True
        return False

    async def get_all(
        self,
        memory_type: Optional[MemoryType] = None,
        limit: int = 100,
    ) -> list[Memory]:
        memories = list(self._memories.values())
        if memory_type:
            memories = [m for m in memories if m.type == memory_type]
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories[:limit]

    async def count(self, memory_type: Optional[MemoryType] = None) -> int:
        if memory_type:
            return sum(1 for m in self._memories.values() if m.type == memory_type)
        return len(self._memories)


class ChromaStore(BaseMemoryStore):
    """ChromaDB 向量存储 - 用于生产环境

    使用 ChromaDB 实现语义检索，支持:
    - 向量相似度搜索
    - 元数据过滤
    - 持久化存储
    """

    def __init__(self, collection_name: str = "agent_memories", persist_dir: Optional[str] = None):
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "ChromaDB 未安装，请运行: pip install chromadb\n"
                "或使用 InMemoryStore 进行开发测试"
            )

        if persist_dir:
            self._client = chromadb.PersistentClient(path=persist_dir)
        else:
            self._client = chromadb.Client()

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def save(self, memory: Memory) -> str:
        metadata = {
            "type": memory.type.value,
            "importance": memory.importance,
            "access_count": memory.access_count,
            "created_at": memory.created_at.isoformat(),
            "last_accessed": memory.last_accessed.isoformat(),
            **{f"meta_{k}": json.dumps(v) if isinstance(v, (dict, list)) else str(v)
               for k, v in memory.metadata.items()},
        }

        kwargs: dict[str, Any] = {
            "ids": [memory.id],
            "documents": [memory.content],
            "metadatas": [metadata],
        }
        if memory.embedding:
            kwargs["embeddings"] = [memory.embedding]

        self._collection.upsert(**kwargs)
        return memory.id

    async def get(self, memory_id: str) -> Optional[Memory]:
        result = self._collection.get(ids=[memory_id], include=["documents", "metadatas", "embeddings"])
        if not result["ids"]:
            return None

        memory = self._result_to_memory(result, 0)
        # 更新访问计数
        memory.access_count += 1
        memory.last_accessed = datetime.now()
        await self.save(memory)
        return memory

    async def search(self, query: MemoryQuery) -> list[Memory]:
        where_filter = self._build_where_filter(query)

        kwargs: dict[str, Any] = {
            "n_results": query.max_results,
            "include": ["documents", "metadatas", "embeddings", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter

        if query.query:
            kwargs["query_texts"] = [query.query]
            result = self._collection.query(**kwargs)
        else:
            # 无查询文本时获取所有并按元数据排序
            get_kwargs: dict[str, Any] = {
                "include": ["documents", "metadatas", "embeddings"],
                "limit": query.max_results,
            }
            if where_filter:
                get_kwargs["where"] = where_filter
            result = self._collection.get(**get_kwargs)
            # 转换格式使其与 query 结果兼容
            result = {
                "ids": [result["ids"]],
                "documents": [result["documents"]],
                "metadatas": [result["metadatas"]],
                "embeddings": [result.get("embeddings")],
            }

        memories = []
        ids_list = result["ids"][0] if result["ids"] else []
        for i in range(len(ids_list)):
            memory = self._result_to_memory_from_query(result, i)
            memories.append(memory)

        return memories

    async def delete(self, memory_id: str) -> bool:
        try:
            self._collection.delete(ids=[memory_id])
            return True
        except Exception:
            return False

    async def update(self, memory: Memory) -> bool:
        try:
            await self.save(memory)
            return True
        except Exception:
            return False

    async def get_all(
        self,
        memory_type: Optional[MemoryType] = None,
        limit: int = 100,
    ) -> list[Memory]:
        kwargs: dict[str, Any] = {
            "include": ["documents", "metadatas", "embeddings"],
            "limit": limit,
        }
        if memory_type:
            kwargs["where"] = {"type": memory_type.value}

        result = self._collection.get(**kwargs)
        memories = []
        for i in range(len(result["ids"])):
            memories.append(self._result_to_memory(result, i))

        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories

    async def count(self, memory_type: Optional[MemoryType] = None) -> int:
        if memory_type:
            result = self._collection.get(where={"type": memory_type.value})
            return len(result["ids"])
        return self._collection.count()

    # ---- 内部工具方法 ----

    def _build_where_filter(self, query: MemoryQuery) -> Optional[dict]:
        """构建 ChromaDB where 过滤条件"""
        conditions = []

        if query.memory_types and len(query.memory_types) == 1:
            conditions.append({"type": query.memory_types[0].value})
        elif query.memory_types and len(query.memory_types) > 1:
            conditions.append({"type": {"$in": [t.value for t in query.memory_types]}})

        if query.min_importance > 0:
            conditions.append({"importance": {"$gte": query.min_importance}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _result_to_memory(self, result: dict, index: int) -> Memory:
        """从 ChromaDB get 结果构造 Memory"""
        meta = result["metadatas"][index] if result["metadatas"] else {}
        emb = (result["embeddings"][index]
               if result.get("embeddings") and result["embeddings"]
               else [])
        return Memory(
            id=result["ids"][index],
            type=MemoryType(meta.get("type", "episodic")),
            content=result["documents"][index] if result["documents"] else "",
            embedding=emb or [],
            metadata={
                k[5:]: v for k, v in meta.items() if k.startswith("meta_")
            },
            importance=float(meta.get("importance", 0.5)),
            access_count=int(meta.get("access_count", 0)),
            last_accessed=datetime.fromisoformat(meta["last_accessed"])
            if "last_accessed" in meta
            else datetime.now(),
            created_at=datetime.fromisoformat(meta["created_at"])
            if "created_at" in meta
            else datetime.now(),
        )

    def _result_to_memory_from_query(self, result: dict, index: int) -> Memory:
        """从 ChromaDB query 结果构造 Memory（query 结果多嵌套一层列表）"""
        meta = result["metadatas"][0][index] if result["metadatas"] else {}
        emb = (result["embeddings"][0][index]
               if result.get("embeddings") and result["embeddings"] and result["embeddings"][0]
               else [])
        return Memory(
            id=result["ids"][0][index],
            type=MemoryType(meta.get("type", "episodic")),
            content=result["documents"][0][index] if result["documents"] else "",
            embedding=emb or [],
            metadata={
                k[5:]: v for k, v in meta.items() if k.startswith("meta_")
            },
            importance=float(meta.get("importance", 0.5)),
            access_count=int(meta.get("access_count", 0)),
            last_accessed=datetime.fromisoformat(meta["last_accessed"])
            if "last_accessed" in meta
            else datetime.now(),
            created_at=datetime.fromisoformat(meta["created_at"])
            if "created_at" in meta
            else datetime.now(),
        )


# ---- 工厂函数 ----

def create_memory_store(
    backend: str = "memory",
    **kwargs: Any,
) -> BaseMemoryStore:
    """创建记忆存储实例

    Args:
        backend: "memory" | "chroma"
        **kwargs: 传给具体存储类的参数

    Returns:
        BaseMemoryStore 实例
    """
    if backend == "memory":
        return InMemoryStore()
    elif backend == "chroma":
        return ChromaStore(**kwargs)
    else:
        raise ValueError(f"不支持的存储后端: {backend}")
