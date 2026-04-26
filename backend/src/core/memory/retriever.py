"""记忆检索器 - 智能记忆召回策略

结合多种信号对记忆进行排序:
- 语义相关性（关键词/向量匹配）
- 时间衰减（越久远的记忆权重越低）
- 重要性评分
- 访问频率
"""
import math
from datetime import datetime
from typing import Any, Optional

from .types import Memory, MemoryQuery, MemoryType
from .store import BaseMemoryStore


class MemoryRetriever:
    """记忆检索器

    从存储中检索记忆，并使用多信号加权排序。
    """

    def __init__(
        self,
        store: BaseMemoryStore,
        relevance_weight: float = 0.4,
        recency_weight: float = 0.3,
        importance_weight: float = 0.2,
        frequency_weight: float = 0.1,
        time_decay_hours: float = 168.0,  # 一周衰减到约 0.37
    ):
        self.store = store
        self.relevance_weight = relevance_weight
        self.recency_weight = recency_weight
        self.importance_weight = importance_weight
        self.frequency_weight = frequency_weight
        self.time_decay_hours = time_decay_hours

    async def retrieve(
        self,
        context: str,
        memory_types: Optional[list[MemoryType]] = None,
        max_results: int = 5,
        min_importance: float = 0.0,
    ) -> list[Memory]:
        """检索与上下文相关的记忆

        Args:
            context: 当前上下文/查询文本
            memory_types: 限定记忆类型
            max_results: 最大返回数量
            min_importance: 最低重要性阈值

        Returns:
            按综合得分排序的记忆列表
        """
        scored = await self.retrieve_with_scores(
            context=context,
            memory_types=memory_types,
            max_results=max_results,
            min_importance=min_importance,
        )
        return [item["memory"] for item in scored]

    async def retrieve_with_scores(
        self,
        context: str,
        memory_types: Optional[list[MemoryType]] = None,
        max_results: int = 5,
        min_importance: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Retrieve memories with non-persistent score explanations."""

        query_text = context.strip()
        if query_text:
            candidate_limit = min(max(max_results * 10, 50), 10000)
            candidates = await self.store.search(
                MemoryQuery(
                    query=query_text,
                    memory_types=memory_types,
                    max_results=candidate_limit,
                    min_importance=min_importance,
                )
            )
        else:
            candidates = await self.store.get_all(limit=10000)
            if memory_types:
                candidates = [m for m in candidates if m.type in memory_types]
            candidates = [m for m in candidates if m.importance >= min_importance]

        if not candidates:
            return []

        scored: list[dict[str, Any]] = []
        now = datetime.now()
        max_access = max(m.access_count for m in candidates) or 1

        for memory in candidates:
            relevance_score = self._relevance_score(context, memory)
            if context and relevance_score <= 0:
                continue

            recent_at = max(memory.created_at, memory.last_accessed)
            hours_ago = max(0.0, (now - recent_at).total_seconds() / 3600)
            recency_score = math.exp(-hours_ago / self.time_decay_hours)
            importance_score = memory.importance
            frequency_score = memory.access_count / max_access

            total_score = (
                self.relevance_weight * relevance_score
                + self.recency_weight * recency_score
                + self.importance_weight * importance_score
                + self.frequency_weight * frequency_score
            )

            scored.append(
                {
                    "memory": memory,
                    "retrieval": {
                        "score": round(total_score, 6),
                        "breakdown": {
                            "relevance": round(relevance_score, 6),
                            "importance": round(importance_score, 6),
                            "recency": round(recency_score, 6),
                            "frequency": round(frequency_score, 6),
                        },
                        "deduped_similar_ids": [],
                    },
                }
            )

        scored.sort(key=lambda item: item["retrieval"]["score"], reverse=True)
        results = self._dedupe_scored(scored)

        selected = results[:max_results]
        for item in selected:
            memory = item["memory"]
            memory.access_count += 1
            memory.last_accessed = datetime.now()
            await self.store.update(memory)

        return selected

    async def get_recent(self, limit: int = 10) -> list[Memory]:
        """获取最近的记忆"""
        return await self.store.get_all(limit=limit)

    async def get_important(
        self,
        limit: int = 10,
        min_importance: float = 0.7,
    ) -> list[Memory]:
        """获取重要记忆"""
        query = MemoryQuery(
            max_results=limit,
            min_importance=min_importance,
        )
        return await self.store.search(query)

    async def get_by_type(
        self,
        memory_type: MemoryType,
        limit: int = 10,
    ) -> list[Memory]:
        """按类型获取记忆"""
        return await self.store.get_all(memory_type=memory_type, limit=limit)

    def _dedupe_scored(self, scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in scored:
            memory = item["memory"]
            duplicate_of = None
            for existing in results:
                if self._memory_similarity(memory, existing["memory"]) >= 0.86:
                    duplicate_of = existing
                    break
            if duplicate_of:
                duplicate_of["retrieval"]["deduped_similar_ids"].append(memory.id)
            else:
                results.append(item)
        return results

    def _memory_similarity(self, left: Memory, right: Memory) -> float:
        left_summary = self._canonical_text(left)
        right_summary = self._canonical_text(right)
        if left_summary and left_summary == right_summary:
            return 1.0
        left_text = self._searchable_text(left)
        right_text = self._searchable_text(right)
        return self._jaccard(left_text, right_text)

    @staticmethod
    def _canonical_text(memory: Memory) -> str:
        metadata = memory.metadata or {}
        return "".join(str(metadata.get("canonical_summary") or memory.content).lower().split())

    def _relevance_score(self, context: str, memory: Memory) -> float:
        query = context.strip().lower()
        if not query:
            return 1.0

        text = self._searchable_text(memory)
        if query in text:
            return 1.0

        query_tokens = self._token_set(query)
        text_tokens = self._token_set(text)
        if not query_tokens or not text_tokens:
            return 0.0

        overlap = query_tokens & text_tokens
        return len(overlap) / len(query_tokens)

    @staticmethod
    def _searchable_text(memory: Memory) -> str:
        metadata = memory.metadata or {}
        pieces = [
            memory.content,
            str(metadata.get("canonical_summary") or ""),
            str(metadata.get("assistant_context") or ""),
            MemoryRetriever._join_metadata_list(metadata.get("topics")),
            MemoryRetriever._join_metadata_list(metadata.get("key_facts")),
        ]
        return " ".join(piece for piece in pieces if piece).lower()

    @staticmethod
    def _join_metadata_list(value: Any) -> str:
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value or "")

    @staticmethod
    def _jaccard(left: str, right: str) -> float:
        left_tokens = MemoryRetriever._token_set(left)
        right_tokens = MemoryRetriever._token_set(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    @staticmethod
    def _token_set(value: str) -> set[str]:
        cleaned = "".join(str(value).lower().split())
        cjk_chars = {ch for ch in cleaned if "\u4e00" <= ch <= "\u9fff"}
        words = set(str(value).lower().split())
        ascii_words = {
            token
            for token in words
            if any(ch.isalnum() for ch in token)
        }
        return cjk_chars | ascii_words
