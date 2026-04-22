"""记忆检索器 - 智能记忆召回策略

结合多种信号对记忆进行排序:
- 语义相关性（关键词/向量匹配）
- 时间衰减（越久远的记忆权重越低）
- 重要性评分
- 访问频率
"""
import math
from datetime import datetime
from typing import Optional

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
        # 先从存储中粗筛（取多一些候选）
        query = MemoryQuery(
            query=context,
            memory_types=memory_types,
            max_results=max_results * 3,  # 粗筛取3倍
            min_importance=min_importance,
        )
        candidates = await self.store.search(query)

        if not candidates:
            return []

        # 计算综合得分
        scored = []
        now = datetime.now()
        max_access = max(m.access_count for m in candidates) or 1

        for rank, memory in enumerate(candidates):
            # 1. 相关性得分（基于搜索排名，rank 0 = 最相关）
            relevance_score = 1.0 / (1 + rank * 0.2)

            # 2. 时间衰减得分
            hours_ago = (now - memory.created_at).total_seconds() / 3600
            recency_score = math.exp(-hours_ago / self.time_decay_hours)

            # 3. 重要性得分
            importance_score = memory.importance

            # 4. 访问频率得分（归一化）
            frequency_score = memory.access_count / max_access

            # 综合加权
            total_score = (
                self.relevance_weight * relevance_score
                + self.recency_weight * recency_score
                + self.importance_weight * importance_score
                + self.frequency_weight * frequency_score
            )

            scored.append((total_score, memory))

        # 按综合得分降序排列
        scored.sort(key=lambda x: x[0], reverse=True)

        return [m for _, m in scored[:max_results]]

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
