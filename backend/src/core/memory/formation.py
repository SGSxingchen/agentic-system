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
from .processor import PRIVATE_MEMORY_SCHEMA_VERSION


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

    async def create_structured_memory(
        self,
        candidate: dict[str, Any],
        *,
        min_quality: float = 0.35,
        min_confidence: float = 0.35,
    ) -> Optional[Memory]:
        """Create a private-assistant memory from a structured candidate.

        Low quality candidates are ignored. Exact or near-identical memories
        with the same ``memory_kind`` are merged into the existing memory.
        """

        metadata = dict(candidate.get("metadata") or {})
        quality = self._clamp_float(metadata.get("summary_quality"), default=1.0)
        confidence = self._clamp_float(metadata.get("confidence"), default=1.0)
        if quality < min_quality or confidence < min_confidence:
            return None

        canonical_summary = str(
            metadata.get("canonical_summary") or candidate.get("content") or ""
        ).strip()
        if not canonical_summary:
            return None

        memory_kind = str(metadata.get("memory_kind") or "other").strip() or "other"
        metadata = self._with_private_defaults(metadata, canonical_summary, memory_kind)

        existing = await self._find_duplicate(canonical_summary, metadata)
        if existing:
            existing.importance = min(
                1.0,
                max(existing.importance, self._clamp_float(candidate.get("importance"), default=0.5))
                + 0.05,
            )
            existing.access_count += 1
            existing.last_accessed = datetime.now()
            existing.metadata = self._merge_metadata(existing.metadata, metadata)
            await self.store.update(existing)
            return existing

        memory_type = self._coerce_memory_type(candidate.get("memory_type"))
        return await self.create_memory(
            content=canonical_summary,
            memory_type=memory_type,
            importance=self._clamp_float(candidate.get("importance"), default=0.5),
            metadata=metadata,
        )

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
            metadata = memory.metadata or {}
            quality = self._clamp_float(metadata.get("summary_quality"), default=0.0)
            is_active_todo = metadata.get("memory_kind") == "todo"
            should_forget = (
                memory.importance < self.forget_min_importance
                and quality < 0.8
                and memory.last_accessed < cutoff
                and not is_active_todo
            )
            if should_forget:
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

    async def _find_duplicate(
        self,
        canonical_summary: str,
        metadata: dict[str, Any],
    ) -> Optional[Memory]:
        memory_kind = metadata.get("memory_kind")
        target_key = self._normalize_text(canonical_summary)
        all_memories = await self.store.get_all(limit=10000)
        for memory in all_memories:
            current_metadata = memory.metadata or {}
            if current_metadata.get("memory_kind") != memory_kind:
                continue

            current_summary = str(
                current_metadata.get("canonical_summary") or memory.content
            )
            current_key = self._normalize_text(current_summary)
            if current_key == target_key:
                return memory
            if self._jaccard(current_key, target_key) >= 0.86:
                return memory
        return None

    @staticmethod
    def _with_private_defaults(
        metadata: dict[str, Any],
        canonical_summary: str,
        memory_kind: str,
    ) -> dict[str, Any]:
        enriched = dict(metadata)
        enriched["memory_kind"] = memory_kind
        enriched.setdefault("canonical_summary", canonical_summary)
        enriched.setdefault("assistant_context", canonical_summary)
        enriched.setdefault("topics", [])
        enriched.setdefault("key_facts", [])
        enriched.setdefault("source_window", {})
        enriched.setdefault("source", "chat_reflection")
        enriched.setdefault("source_agent", "assistant")
        enriched.setdefault("schema_version", PRIVATE_MEMORY_SCHEMA_VERSION)
        return enriched

    @staticmethod
    def _merge_metadata(
        base: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in incoming.items():
            if key in {"topics", "key_facts"}:
                merged[key] = MemoryFormation._merge_unique_lists(
                    merged.get(key),
                    value,
                )
            elif key == "source_window":
                merged[key] = MemoryFormation._merge_source_windows(
                    merged.get(key),
                    value,
                )
            elif key not in merged or merged[key] in (None, "", [], {}):
                merged[key] = value
            elif key in {"confidence", "summary_quality"}:
                merged[key] = max(
                    MemoryFormation._clamp_float(merged[key], default=0.0),
                    MemoryFormation._clamp_float(value, default=0.0),
                )
        merged.setdefault("schema_version", PRIVATE_MEMORY_SCHEMA_VERSION)
        return merged

    @staticmethod
    def _merge_unique_lists(base: Any, incoming: Any) -> list[str]:
        values: list[str] = []
        for source in (base, incoming):
            if not isinstance(source, list):
                continue
            for item in source:
                text = str(item).strip()
                if text and text not in values:
                    values.append(text)
        return values

    @staticmethod
    def _merge_source_windows(base: Any, incoming: Any) -> Any:
        windows = []
        if isinstance(base, list):
            windows.extend(base)
        elif isinstance(base, dict) and base:
            windows.append(base)
        if isinstance(incoming, list):
            windows.extend(item for item in incoming if isinstance(item, dict))
        elif isinstance(incoming, dict) and incoming:
            windows.append(incoming)
        if not windows:
            return {}
        return windows

    @staticmethod
    def _coerce_memory_type(value: Any) -> MemoryType:
        try:
            return MemoryType(str(value or "semantic"))
        except ValueError:
            return MemoryType.SEMANTIC

    @staticmethod
    def _clamp_float(value: Any, *, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(0.0, min(1.0, number))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return "".join(str(value).lower().split())

    @staticmethod
    def _jaccard(left: str, right: str) -> float:
        left_tokens = MemoryFormation._token_set(left)
        right_tokens = MemoryFormation._token_set(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    @staticmethod
    def _token_set(value: str) -> set[str]:
        if not value:
            return set()
        cjk_chars = {ch for ch in value if "\u4e00" <= ch <= "\u9fff"}
        words = set(value.split())
        return cjk_chars | words
