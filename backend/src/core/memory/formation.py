"""记忆形成与巩固 - 将原始信息转化为结构化记忆

负责:
- 从事件/对话中提取值得记忆的信息
- 评估记忆重要性
- 生成 embedding（如果可用）
- 记忆巩固（重复出现的信息提升重要性）
- 记忆遗忘（长期不访问的低重要性记忆被清除）
"""
from datetime import datetime, timedelta
from typing import Any, Optional

from .types import Memory, MemoryType
from .store import BaseMemoryStore


class MemoryFormation:
    """记忆形成与巩固引擎"""

    def __init__(
        self,
        store: BaseMemoryStore,
        embedding_fn: Optional[Any] = None,
        consolidation_threshold: float = 0.3,
        forget_after_days: int = 30,
        forget_min_importance: float = 0.3,
    ):
        """
        Args:
            store: 记忆存储
            embedding_fn: 可选的 embedding 函数 (async str -> list[float])
            consolidation_threshold: 相似记忆巩固的阈值
            forget_after_days: 多少天不访问后考虑遗忘
            forget_min_importance: 低于此重要性 + 超时 → 遗忘
        """
        self.store = store
        self.embedding_fn = embedding_fn
        self.consolidation_threshold = consolidation_threshold
        self.forget_after_days = forget_after_days
        self.forget_min_importance = forget_min_importance

    async def create_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        importance: float = 0.5,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Memory:
        """创建新记忆

        自动处理:
        1. 生成 embedding（如果 embedding_fn 可用）
        2. 保存到存储
        """
        # 生成 embedding
        embedding = []
        if self.embedding_fn:
            try:
                embedding = await self.embedding_fn(content)
            except Exception as e:
                print(f"[WARN] Embedding 生成失败: {e}")

        memory = Memory(
            type=memory_type,
            content=content,
            embedding=embedding,
            importance=importance,
            metadata=metadata or {},
        )

        await self.store.save(memory)
        return memory

    async def create_episodic(
        self,
        event_description: str,
        source: str = "",
        importance: float = 0.5,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> Memory:
        """创建情景记忆（记录发生的事件）"""
        metadata = {"source": source}
        if extra_metadata:
            metadata.update(extra_metadata)

        return await self.create_memory(
            content=event_description,
            memory_type=MemoryType.EPISODIC,
            importance=importance,
            metadata=metadata,
        )

    async def create_semantic(
        self,
        fact: str,
        category: str = "",
        importance: float = 0.6,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> Memory:
        """创建语义记忆（记录事实和知识）"""
        metadata = {"category": category}
        if extra_metadata:
            metadata.update(extra_metadata)

        return await self.create_memory(
            content=fact,
            memory_type=MemoryType.SEMANTIC,
            importance=importance,
            metadata=metadata,
        )

    async def create_procedural(
        self,
        pattern: str,
        context: str = "",
        importance: float = 0.7,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> Memory:
        """创建程序性记忆（记录技能和模式）"""
        metadata = {"context": context}
        if extra_metadata:
            metadata.update(extra_metadata)

        return await self.create_memory(
            content=pattern,
            memory_type=MemoryType.PROCEDURAL,
            importance=importance,
            metadata=metadata,
        )

    async def consolidate(self) -> dict[str, int]:
        """记忆巩固 - 处理重复和相关记忆

        策略:
        - 完全相同内容 → 合并，提升重要性
        - 高度相似内容 → 标记关联

        Returns:
            {"merged": 合并数, "strengthened": 强化数}
        """
        stats = {"merged": 0, "strengthened": 0}
        all_memories = await self.store.get_all(limit=1000)

        # 按内容分组查找重复
        content_map: dict[str, list[Memory]] = {}
        for memory in all_memories:
            # 简单的归一化 key（去首尾空格 + 小写）
            key = memory.content.strip().lower()
            if key not in content_map:
                content_map[key] = []
            content_map[key].append(memory)

        # 处理重复
        for key, memories in content_map.items():
            if len(memories) <= 1:
                continue

            # 保留最早的，合并其余
            memories.sort(key=lambda m: m.created_at)
            primary = memories[0]

            for duplicate in memories[1:]:
                # 提升重要性
                primary.importance = min(1.0, primary.importance + 0.1)
                primary.access_count += duplicate.access_count
                # 合并元数据
                primary.metadata.update(duplicate.metadata)
                # 删除重复
                await self.store.delete(duplicate.id)
                stats["merged"] += 1

            await self.store.update(primary)
            stats["strengthened"] += 1

        return stats

    async def forget(self) -> int:
        """记忆遗忘 - 清除过期的低重要性记忆

        条件:
        - 重要性 < forget_min_importance
        - 最后访问时间 > forget_after_days 天前

        Returns:
            被遗忘的记忆数量
        """
        forgotten = 0
        cutoff = datetime.now() - timedelta(days=self.forget_after_days)
        all_memories = await self.store.get_all(limit=10000)

        for memory in all_memories:
            if (
                memory.importance < self.forget_min_importance
                and memory.last_accessed < cutoff
            ):
                await self.store.delete(memory.id)
                forgotten += 1

        return forgotten

    async def get_stats(self) -> dict[str, Any]:
        """获取记忆系统统计信息"""
        total = await self.store.count()
        episodic = await self.store.count(MemoryType.EPISODIC)
        semantic = await self.store.count(MemoryType.SEMANTIC)
        procedural = await self.store.count(MemoryType.PROCEDURAL)

        return {
            "total": total,
            "by_type": {
                "episodic": episodic,
                "semantic": semantic,
                "procedural": procedural,
            },
        }
