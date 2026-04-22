"""上下文存储补充测试

覆盖:
- 持久化读写
- 并发操作
- 作用域隔离
- 边界情况
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from core.context.store import ContextStore, ContextScope


# =====================
# 持久化测试
# =====================

class TestContextPersistence:

    async def test_save_and_load_project_context(self, tmp_path):
        store = ContextStore(persist_dir=str(tmp_path))
        await store.set("repo_url", "https://github.com/test", ContextScope.PROJECT)
        await store.set("version", "1.0.0", ContextScope.PROJECT)
        await store.save_project_context()

        # 创建新 store 实例并加载
        store2 = ContextStore(persist_dir=str(tmp_path))
        await store2.load_project_context()

        url = await store2.get("repo_url", ContextScope.PROJECT)
        version = await store2.get("version", ContextScope.PROJECT)
        assert url == "https://github.com/test"
        assert version == "1.0.0"

    async def test_save_without_persist_dir(self):
        store = ContextStore()
        await store.set("key", "value", ContextScope.PROJECT)
        # 无持久化目录，save 不应报错
        await store.save_project_context()

    async def test_load_nonexistent_file(self, tmp_path):
        store = ContextStore(persist_dir=str(tmp_path))
        # 文件不存在，load 不应报错
        await store.load_project_context()
        result = await store.get("anything", ContextScope.PROJECT)
        assert result is None

    async def test_persist_complex_data(self, tmp_path):
        store = ContextStore(persist_dir=str(tmp_path))
        data = {
            "tasks": [
                {"name": "task1", "done": True},
                {"name": "task2", "done": False},
            ],
            "meta": {"count": 2, "tags": ["a", "b"]},
        }
        await store.set("project_data", data, ContextScope.PROJECT)
        await store.save_project_context()

        store2 = ContextStore(persist_dir=str(tmp_path))
        await store2.load_project_context()
        loaded = await store2.get("project_data", ContextScope.PROJECT)
        assert loaded["tasks"][0]["name"] == "task1"
        assert loaded["meta"]["count"] == 2

    async def test_persist_file_format(self, tmp_path):
        """验证持久化文件是 JSON 格式"""
        store = ContextStore(persist_dir=str(tmp_path))
        await store.set("key", "value", ContextScope.PROJECT)
        await store.save_project_context()

        file_path = tmp_path / "project_context.json"
        assert file_path.exists()
        content = json.loads(file_path.read_text(encoding="utf-8"))
        assert content["key"] == "value"


# =====================
# 作用域隔离测试
# =====================

class TestContextScopeIsolation:

    async def test_same_key_different_scopes(self):
        store = ContextStore()
        await store.set("name", "project_name", ContextScope.PROJECT)
        await store.set("name", "session_name", ContextScope.SESSION)
        await store.set("name", "agent_name", ContextScope.AGENT, agent_id="coder")

        assert await store.get("name", ContextScope.PROJECT) == "project_name"
        assert await store.get("name", ContextScope.SESSION) == "session_name"
        assert await store.get("name", ContextScope.AGENT, agent_id="coder") == "agent_name"

    async def test_agent_scope_isolation(self):
        store = ContextStore()
        await store.set("task", "编码", ContextScope.AGENT, agent_id="coder")
        await store.set("task", "审查", ContextScope.AGENT, agent_id="reviewer")

        assert await store.get("task", ContextScope.AGENT, agent_id="coder") == "编码"
        assert await store.get("task", ContextScope.AGENT, agent_id="reviewer") == "审查"

    async def test_clear_session_not_affect_project(self):
        store = ContextStore()
        await store.set("key", "project_val", ContextScope.PROJECT)
        await store.set("key", "session_val", ContextScope.SESSION)

        await store.clear(ContextScope.SESSION)

        assert await store.get("key", ContextScope.PROJECT) == "project_val"
        assert await store.get("key", ContextScope.SESSION) is None

    async def test_clear_agent_specific(self):
        store = ContextStore()
        await store.set("x", 1, ContextScope.AGENT, agent_id="coder")
        await store.set("x", 2, ContextScope.AGENT, agent_id="reviewer")

        await store.clear(ContextScope.AGENT, agent_id="coder")

        assert await store.get("x", ContextScope.AGENT, agent_id="coder") is None
        assert await store.get("x", ContextScope.AGENT, agent_id="reviewer") == 2

    async def test_clear_all_agents(self):
        store = ContextStore()
        await store.set("x", 1, ContextScope.AGENT, agent_id="a")
        await store.set("x", 2, ContextScope.AGENT, agent_id="b")

        await store.clear(ContextScope.AGENT)

        assert await store.get("x", ContextScope.AGENT, agent_id="a") is None
        assert await store.get("x", ContextScope.AGENT, agent_id="b") is None

    async def test_agent_scope_requires_agent_id(self):
        store = ContextStore()
        with pytest.raises(ValueError, match="agent_id"):
            await store.get("key", ContextScope.AGENT)


# =====================
# CRUD 边界测试
# =====================

class TestContextCRUDEdgeCases:

    async def test_get_nonexistent_key(self):
        store = ContextStore()
        result = await store.get("nonexistent")
        assert result is None

    async def test_get_with_default(self):
        store = ContextStore()
        result = await store.get("missing", default="fallback")
        assert result == "fallback"

    async def test_delete_nonexistent_key(self):
        store = ContextStore()
        result = await store.delete("nonexistent")
        assert result is False

    async def test_delete_existing_key(self):
        store = ContextStore()
        await store.set("key", "value")
        result = await store.delete("key")
        assert result is True
        assert await store.get("key") is None

    async def test_get_all_empty(self):
        store = ContextStore()
        result = await store.get_all()
        assert result == {}

    async def test_get_all_returns_copy(self):
        store = ContextStore()
        await store.set("a", 1)
        all_data = await store.get_all()
        all_data["a"] = 999
        # 原始数据不受影响
        assert await store.get("a") == 1

    async def test_set_overwrite(self):
        store = ContextStore()
        await store.set("key", "v1")
        await store.set("key", "v2")
        assert await store.get("key") == "v2"

    async def test_none_value(self):
        store = ContextStore()
        await store.set("key", None)
        assert await store.get("key") is None
        assert await store.get("key", default="default") is None  # None is stored, not missing


# =====================
# 并发测试
# =====================

class TestContextConcurrency:

    async def test_concurrent_writes(self):
        store = ContextStore()

        async def writer(key, value):
            await store.set(key, value)

        tasks = [writer(f"key_{i}", i) for i in range(100)]
        await asyncio.gather(*tasks)

        for i in range(100):
            assert await store.get(f"key_{i}") == i

    async def test_concurrent_read_write(self):
        store = ContextStore()
        await store.set("counter", 0)

        async def increment():
            val = await store.get("counter")
            await store.set("counter", val + 1)

        # 并发写入 — 由于锁的保护，最终值取决于执行顺序
        tasks = [increment() for _ in range(10)]
        await asyncio.gather(*tasks)

        # 值应该在 1-10 之间（取决于锁的行为）
        result = await store.get("counter")
        assert result >= 1
