"""记忆系统单元测试"""
import asyncio
import sys
from pathlib import Path

# 修复导入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from core.memory import (
    Memory,
    MemoryType,
    MemoryQuery,
    InMemoryStore,
    MemoryRetriever,
    MemoryFormation,
)


# =====================
# MemoryStore 测试
# =====================


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def formation(store):
    return MemoryFormation(store=store)


@pytest.fixture
def retriever(store):
    return MemoryRetriever(store=store)


class TestInMemoryStore:
    """内存存储测试"""

    async def test_save_and_get(self, store):
        memory = Memory(content="测试记忆", importance=0.8)
        saved_id = await store.save(memory)
        assert saved_id == memory.id

        retrieved = await store.get(saved_id)
        assert retrieved is not None
        assert retrieved.content == "测试记忆"
        assert retrieved.importance == 0.8

    async def test_get_nonexistent(self, store):
        result = await store.get("nonexistent-id")
        assert result is None

    async def test_delete(self, store):
        memory = Memory(content="要删除的记忆")
        await store.save(memory)

        success = await store.delete(memory.id)
        assert success is True

        result = await store.get(memory.id)
        assert result is None

    async def test_delete_nonexistent(self, store):
        success = await store.delete("nonexistent-id")
        assert success is False

    async def test_search_by_keyword(self, store):
        await store.save(Memory(content="Python 是一门编程语言", importance=0.5))
        await store.save(Memory(content="TypeScript 用于前端开发", importance=0.6))
        await store.save(Memory(content="Python 支持异步编程", importance=0.7))

        query = MemoryQuery(query="Python", max_results=5)
        results = await store.search(query)

        assert len(results) == 2
        assert all("Python" in m.content for m in results)

    async def test_search_by_type(self, store):
        await store.save(
            Memory(content="事件1", type=MemoryType.EPISODIC)
        )
        await store.save(
            Memory(content="知识1", type=MemoryType.SEMANTIC)
        )
        await store.save(
            Memory(content="模式1", type=MemoryType.PROCEDURAL)
        )

        query = MemoryQuery(
            memory_types=[MemoryType.SEMANTIC],
            max_results=10,
        )
        results = await store.search(query)

        assert len(results) == 1
        assert results[0].content == "知识1"

    async def test_search_by_importance(self, store):
        await store.save(Memory(content="不重要的", importance=0.2))
        await store.save(Memory(content="重要的", importance=0.8))
        await store.save(Memory(content="非常重要的", importance=0.95))

        query = MemoryQuery(min_importance=0.7, max_results=10)
        results = await store.search(query)

        assert len(results) == 2

    async def test_count(self, store):
        await store.save(Memory(content="记忆1", type=MemoryType.EPISODIC))
        await store.save(Memory(content="记忆2", type=MemoryType.SEMANTIC))
        await store.save(Memory(content="记忆3", type=MemoryType.EPISODIC))

        assert await store.count() == 3
        assert await store.count(MemoryType.EPISODIC) == 2
        assert await store.count(MemoryType.SEMANTIC) == 1
        assert await store.count(MemoryType.PROCEDURAL) == 0

    async def test_get_all(self, store):
        for i in range(5):
            await store.save(Memory(content=f"记忆{i}"))

        all_memories = await store.get_all(limit=3)
        assert len(all_memories) == 3

    async def test_update(self, store):
        memory = Memory(content="原始内容", importance=0.5)
        await store.save(memory)

        memory.content = "更新后的内容"
        memory.importance = 0.9
        success = await store.update(memory)
        assert success is True

        updated = await store.get(memory.id)
        assert updated.content == "更新后的内容"
        assert updated.importance == 0.9


# =====================
# MemoryFormation 测试
# =====================


class TestMemoryFormation:
    """记忆形成测试"""

    async def test_create_episodic(self, formation):
        memory = await formation.create_episodic(
            event_description="用户要求生成登录功能",
            source="assistant",
            importance=0.6,
        )
        assert memory.type == MemoryType.EPISODIC
        assert memory.content == "用户要求生成登录功能"
        assert memory.metadata["source"] == "assistant"

    async def test_create_semantic(self, formation):
        memory = await formation.create_semantic(
            fact="用户偏好使用 TypeScript",
            category="user_preference",
            importance=0.7,
        )
        assert memory.type == MemoryType.SEMANTIC
        assert memory.metadata["category"] == "user_preference"

    async def test_create_procedural(self, formation):
        memory = await formation.create_procedural(
            pattern="用户喜欢简洁的代码风格",
            context="code_generation",
        )
        assert memory.type == MemoryType.PROCEDURAL

    async def test_consolidate_duplicates(self, formation, store):
        # 创建重复记忆
        await formation.create_semantic(fact="Python 是一门编程语言")
        await formation.create_semantic(fact="Python 是一门编程语言")
        await formation.create_semantic(fact="Python 是一门编程语言")

        assert await store.count() == 3

        stats = await formation.consolidate()
        assert stats["merged"] == 2  # 2个重复被合并
        assert await store.count() == 1  # 只剩1个

    async def test_forget(self, formation, store):
        from datetime import datetime, timedelta

        # 创建一个很旧且不重要的记忆
        old_memory = Memory(
            content="不重要的旧记忆",
            importance=0.1,
            last_accessed=datetime.now() - timedelta(days=60),
            created_at=datetime.now() - timedelta(days=60),
        )
        await store.save(old_memory)

        # 创建一个新的重要记忆
        await formation.create_semantic(
            fact="重要的新知识",
            importance=0.9,
        )

        assert await store.count() == 2

        forgotten = await formation.forget()
        assert forgotten == 1
        assert await store.count() == 1

    async def test_get_stats(self, formation):
        await formation.create_episodic("事件1")
        await formation.create_episodic("事件2")
        await formation.create_semantic("知识1")
        await formation.create_procedural("模式1")

        stats = await formation.get_stats()
        assert stats["total"] == 4
        assert stats["by_type"]["episodic"] == 2
        assert stats["by_type"]["semantic"] == 1
        assert stats["by_type"]["procedural"] == 1


# =====================
# MemoryRetriever 测试
# =====================


class TestMemoryRetriever:
    """记忆检索测试"""

    async def test_retrieve_relevant(self, retriever, store):
        await store.save(
            Memory(content="Python asyncio 异步编程", importance=0.7)
        )
        await store.save(
            Memory(content="React 组件开发", importance=0.5)
        )
        await store.save(
            Memory(content="Python FastAPI web框架", importance=0.8)
        )

        results = await retriever.retrieve(
            context="Python web 开发",
            max_results=2,
        )

        assert len(results) <= 2
        # 应该返回 Python 相关的记忆
        assert any("Python" in m.content for m in results)

    async def test_retrieve_by_type(self, retriever, store):
        await store.save(
            Memory(
                content="用户喜欢 TypeScript",
                type=MemoryType.SEMANTIC,
                importance=0.7,
            )
        )
        await store.save(
            Memory(
                content="上次生成了登录功能",
                type=MemoryType.EPISODIC,
                importance=0.5,
            )
        )

        results = await retriever.get_by_type(MemoryType.SEMANTIC)
        assert len(results) == 1
        assert results[0].type == MemoryType.SEMANTIC

    async def test_retrieve_empty(self, retriever):
        results = await retriever.retrieve(context="任何内容")
        assert results == []

    async def test_get_important(self, retriever, store):
        await store.save(Memory(content="不重要", importance=0.2))
        await store.save(Memory(content="很重要", importance=0.9))
        await store.save(Memory(content="中等重要", importance=0.5))

        results = await retriever.get_important(min_importance=0.7)
        assert len(results) == 1
        assert results[0].content == "很重要"


# =====================
# Memory 序列化测试
# =====================


class TestMemorySerialization:
    """记忆序列化测试"""

    def test_to_dict(self):
        memory = Memory(
            content="测试内容",
            type=MemoryType.SEMANTIC,
            importance=0.8,
            metadata={"key": "value"},
        )
        d = memory.to_dict()

        assert d["content"] == "测试内容"
        assert d["type"] == "semantic"
        assert d["importance"] == 0.8
        assert d["metadata"]["key"] == "value"

    def test_from_dict(self):
        data = {
            "content": "反序列化测试",
            "type": "procedural",
            "importance": 0.6,
            "metadata": {"source": "test"},
        }
        memory = Memory.from_dict(data)

        assert memory.content == "反序列化测试"
        assert memory.type == MemoryType.PROCEDURAL
        assert memory.importance == 0.6

    def test_roundtrip(self):
        original = Memory(
            content="往返测试",
            type=MemoryType.EPISODIC,
            importance=0.75,
            metadata={"a": 1, "b": "two"},
        )
        d = original.to_dict()
        restored = Memory.from_dict(d)

        assert restored.content == original.content
        assert restored.type == original.type
        assert restored.importance == original.importance
        assert restored.metadata == original.metadata
