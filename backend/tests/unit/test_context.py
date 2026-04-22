"""上下文存储 - 单元测试"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.context.store import ContextStore, ContextScope


@pytest.fixture
def store():
    """内存模式的 ContextStore"""
    return ContextStore()


@pytest.fixture
def persistent_store(tmp_path):
    """带持久化的 ContextStore"""
    return ContextStore(persist_dir=str(tmp_path))


# ─── 基本 CRUD ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_and_get_session(store: ContextStore):
    """SESSION 作用域基本读写"""
    await store.set("key1", "value1", ContextScope.SESSION)
    result = await store.get("key1", ContextScope.SESSION)
    assert result == "value1"


@pytest.mark.asyncio
async def test_set_and_get_project(store: ContextStore):
    """PROJECT 作用域基本读写"""
    await store.set("repo", "https://github.com/test", ContextScope.PROJECT)
    result = await store.get("repo", ContextScope.PROJECT)
    assert result == "https://github.com/test"


@pytest.mark.asyncio
async def test_set_and_get_agent(store: ContextStore):
    """AGENT 作用域基本读写"""
    await store.set("scratchpad", "notes", ContextScope.AGENT, agent_id="coder")
    result = await store.get("scratchpad", ContextScope.AGENT, agent_id="coder")
    assert result == "notes"


@pytest.mark.asyncio
async def test_agent_scope_requires_agent_id(store: ContextStore):
    """AGENT 作用域必须提供 agent_id"""
    with pytest.raises(ValueError, match="agent_id"):
        await store.set("key", "value", ContextScope.AGENT)


@pytest.mark.asyncio
async def test_get_default(store: ContextStore):
    """不存在的 key 返回 default"""
    result = await store.get("nonexistent", ContextScope.SESSION, default="fallback")
    assert result == "fallback"


@pytest.mark.asyncio
async def test_get_none_default(store: ContextStore):
    """不存在的 key 默认返回 None"""
    result = await store.get("nonexistent", ContextScope.SESSION)
    assert result is None


# ─── 删除 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_existing(store: ContextStore):
    """删除已存在的 key"""
    await store.set("to_delete", "value", ContextScope.SESSION)
    deleted = await store.delete("to_delete", ContextScope.SESSION)
    assert deleted is True
    assert await store.get("to_delete", ContextScope.SESSION) is None


@pytest.mark.asyncio
async def test_delete_nonexistent(store: ContextStore):
    """删除不存在的 key 返回 False"""
    deleted = await store.delete("ghost", ContextScope.SESSION)
    assert deleted is False


# ─── get_all / clear ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all(store: ContextStore):
    """获取某作用域所有上下文"""
    await store.set("a", 1, ContextScope.SESSION)
    await store.set("b", 2, ContextScope.SESSION)
    all_ctx = await store.get_all(ContextScope.SESSION)
    assert all_ctx == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_get_all_returns_copy(store: ContextStore):
    """get_all 返回的是副本，修改不影响原始"""
    await store.set("x", 10, ContextScope.SESSION)
    all_ctx = await store.get_all(ContextScope.SESSION)
    all_ctx["x"] = 999
    assert await store.get("x", ContextScope.SESSION) == 10


@pytest.mark.asyncio
async def test_clear_session(store: ContextStore):
    """清空 SESSION 作用域"""
    await store.set("a", 1, ContextScope.SESSION)
    await store.set("b", 2, ContextScope.SESSION)
    await store.clear(ContextScope.SESSION)
    assert await store.get_all(ContextScope.SESSION) == {}


@pytest.mark.asyncio
async def test_clear_agent_by_id(store: ContextStore):
    """清空特定 agent 的上下文"""
    await store.set("k", "v", ContextScope.AGENT, agent_id="a1")
    await store.set("k", "v", ContextScope.AGENT, agent_id="a2")
    await store.clear(ContextScope.AGENT, agent_id="a1")
    # a1 被清空
    assert await store.get("k", ContextScope.AGENT, agent_id="a1") is None
    # a2 不受影响
    assert await store.get("k", ContextScope.AGENT, agent_id="a2") == "v"


@pytest.mark.asyncio
async def test_clear_all_agents(store: ContextStore):
    """清空所有 agent 上下文"""
    await store.set("k", "v", ContextScope.AGENT, agent_id="a1")
    await store.set("k", "v", ContextScope.AGENT, agent_id="a2")
    await store.clear(ContextScope.AGENT)
    assert await store.get("k", ContextScope.AGENT, agent_id="a1") is None
    assert await store.get("k", ContextScope.AGENT, agent_id="a2") is None


# ─── 作用域隔离 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_isolation(store: ContextStore):
    """不同作用域互不干扰"""
    await store.set("key", "project_val", ContextScope.PROJECT)
    await store.set("key", "session_val", ContextScope.SESSION)
    await store.set("key", "agent_val", ContextScope.AGENT, agent_id="coder")

    assert await store.get("key", ContextScope.PROJECT) == "project_val"
    assert await store.get("key", ContextScope.SESSION) == "session_val"
    assert await store.get("key", ContextScope.AGENT, agent_id="coder") == "agent_val"


@pytest.mark.asyncio
async def test_agent_isolation(store: ContextStore):
    """不同 agent 的上下文互相隔离"""
    await store.set("note", "coder_note", ContextScope.AGENT, agent_id="coder")
    await store.set("note", "reviewer_note", ContextScope.AGENT, agent_id="reviewer")

    assert await store.get("note", ContextScope.AGENT, agent_id="coder") == "coder_note"
    assert await store.get("note", ContextScope.AGENT, agent_id="reviewer") == "reviewer_note"


# ─── 持久化 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_load_project_context(persistent_store: ContextStore):
    """项目级上下文持久化"""
    await persistent_store.set("repo_url", "https://github.com/test", ContextScope.PROJECT)
    await persistent_store.set("version", "1.0", ContextScope.PROJECT)
    await persistent_store.save_project_context()

    # 创建新实例加载
    new_store = ContextStore(persist_dir=str(persistent_store._persist_path.parent))
    await new_store.load_project_context()

    assert await new_store.get("repo_url", ContextScope.PROJECT) == "https://github.com/test"
    assert await new_store.get("version", ContextScope.PROJECT) == "1.0"


@pytest.mark.asyncio
async def test_load_nonexistent_file():
    """加载不存在的文件不报错"""
    store = ContextStore(persist_dir="/tmp/nonexistent_test_dir_12345")
    await store.load_project_context()  # 不应抛异常
    assert await store.get_all(ContextScope.PROJECT) == {}


@pytest.mark.asyncio
async def test_save_without_persist_dir(store: ContextStore):
    """无 persist_dir 时 save 不报错"""
    await store.set("key", "value", ContextScope.PROJECT)
    await store.save_project_context()  # 静默跳过


# ─── 复杂值 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complex_values(store: ContextStore):
    """支持复杂数据类型"""
    complex_data = {
        "tasks": [
            {"name": "task1", "status": "done"},
            {"name": "task2", "status": "pending"},
        ],
        "metadata": {"count": 42, "nested": {"deep": True}},
    }
    await store.set("workflow", complex_data, ContextScope.SESSION)
    result = await store.get("workflow", ContextScope.SESSION)
    assert result == complex_data
