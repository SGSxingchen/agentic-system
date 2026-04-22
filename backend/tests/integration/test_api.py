"""API 端点集成测试

使用 httpx AsyncClient + ASGITransport 直接测试 FastAPI 路由，
通过预注入依赖来绕过完整的 lifespan 初始化（避免连接真实 LLM）。

测试覆盖:
- /api/health          — 健康检查
- /api/agents          — 智能体列表
- /api/memory/*        — 记忆系统 CRUD
- /api/tasks           — 任务管理
- /api/config          — 配置查询
"""
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from httpx import AsyncClient, ASGITransport

from core.bus import SimpleBus
from core.memory import (
    MemoryFormation,
    MemoryRetriever,
    InMemoryStore,
)
from core.agent import AgentRegistry
from api.dependencies import (
    set_bus,
    set_agent_registry,
    set_memory_store,
    set_memory_formation,
    set_memory_retriever,
    set_reload_agent_fn,
    set_pipeline,
)


# ─── 创建无 lifespan 的测试 App ───────────────────────────

def _create_test_app():
    """创建一个跳过 lifespan 的测试 FastAPI 应用

    复用生产路由，但用空 lifespan 替代原版（不连接 LLM）。
    依赖通过 fixture 中的 set_* 预注入。
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from api.routes import (
        tasks_router,
        agents_router,
        workflows_router,
        memory_router,
        config_router,
    )

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    test_app = FastAPI(lifespan=_noop_lifespan)

    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    test_app.include_router(tasks_router)
    test_app.include_router(agents_router)
    test_app.include_router(workflows_router)
    test_app.include_router(memory_router)
    test_app.include_router(config_router)

    return test_app


# ─── Fixtures ─────────────────────────────────────────────

@pytest.fixture
async def setup_deps():
    """预注入所有依赖到全局 _state，测试结束后清理。"""
    bus = SimpleBus()
    await bus.start()

    registry = AgentRegistry()
    store = InMemoryStore()
    formation = MemoryFormation(store=store)
    retriever = MemoryRetriever(store=store)

    # 创建一个 mock Pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value={"status": "completed"})

    set_bus(bus)
    set_agent_registry(registry)
    set_pipeline(mock_pipeline)
    set_memory_store(store)
    set_memory_formation(formation)
    set_memory_retriever(retriever)
    set_reload_agent_fn(AsyncMock())

    yield {
        "bus": bus,
        "registry": registry,
        "store": store,
        "formation": formation,
        "retriever": retriever,
        "pipeline": mock_pipeline,
    }

    # 清理
    await bus.stop()
    set_bus(None)
    set_agent_registry(None)
    set_pipeline(None)
    set_memory_store(None)
    set_memory_formation(None)
    set_memory_retriever(None)
    set_reload_agent_fn(None)


@pytest.fixture
async def client(setup_deps):
    """创建 httpx 异步测试客户端"""
    app = _create_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ========================
# 健康检查
# ========================

class TestHealthAPI:
    async def test_health_returns_200(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200

    async def test_health_response_structure(self, client):
        resp = await client.get("/api/health")
        body = resp.json()
        assert body["status"] == "ok"
        assert "data" in body
        data = body["data"]
        # 检查关键字段存在
        assert "bus_running" in data
        assert "memory_initialized" in data

    async def test_health_bus_running(self, client):
        resp = await client.get("/api/health")
        data = resp.json()["data"]
        assert data["bus_running"] is True

    async def test_health_memory_initialized(self, client):
        resp = await client.get("/api/health")
        data = resp.json()["data"]
        assert data["memory_initialized"] is True


# ========================
# 智能体管理
# ========================

class TestAgentsAPI:
    async def test_list_agents_returns_200(self, client):
        resp = await client.get("/api/agents")
        assert resp.status_code == 200

    async def test_list_agents_is_list(self, client):
        resp = await client.get("/api/agents")
        body = resp.json()
        assert body["status"] == "ok"
        assert isinstance(body["data"], list)

    async def test_get_nonexistent_agent_returns_404(self, client):
        resp = await client.get("/api/agents/nonexistent")
        assert resp.status_code == 404


# ========================
# 记忆系统
# ========================

class TestMemoryAPI:
    async def test_memory_stats(self, client):
        resp = await client.get("/api/memory/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    async def test_memory_list_empty(self, client):
        resp = await client.get("/api/memory/list")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert isinstance(body["data"], list)

    async def test_create_memory(self, client):
        resp = await client.post(
            "/api/memory/create",
            json={
                "content": "这是一条测试记忆",
                "type": "semantic",
                "importance": 0.7,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"] is not None

    async def test_create_and_list_memory(self, client):
        # 创建
        resp1 = await client.post(
            "/api/memory/create",
            json={
                "content": "集成测试记忆",
                "type": "semantic",
                "importance": 0.5,
            },
        )
        assert resp1.status_code == 200

        # 列出
        resp2 = await client.get("/api/memory/list")
        assert resp2.status_code == 200
        memories = resp2.json()["data"]
        assert len(memories) >= 1
        # 验证创建的记忆在列表中
        contents = [m.get("content", "") for m in memories]
        assert "集成测试记忆" in contents

    async def test_create_memory_invalid_type(self, client):
        resp = await client.post(
            "/api/memory/create",
            json={
                "content": "测试",
                "type": "invalid_type_xyz",
                "importance": 0.5,
            },
        )
        assert resp.status_code == 200  # API 返回 200 但 status=error
        body = resp.json()
        assert body["status"] == "error"

    async def test_search_memory(self, client):
        # 先创建
        await client.post(
            "/api/memory/create",
            json={
                "content": "Python 是一门编程语言",
                "type": "semantic",
                "importance": 0.8,
            },
        )
        # 搜索
        resp = await client.post(
            "/api/memory/search",
            json={"query": "Python", "max_results": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    async def test_delete_nonexistent_memory(self, client):
        resp = await client.delete("/api/memory/fake-id-12345")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"

    async def test_consolidate(self, client):
        resp = await client.post("/api/memory/consolidate")
        assert resp.status_code == 200

    async def test_forget(self, client):
        resp = await client.post("/api/memory/forget")
        assert resp.status_code == 200


# ========================
# 任务管理
# ========================

class TestTasksAPI:
    async def test_list_tasks_empty(self, client):
        resp = await client.get("/api/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert isinstance(body["data"], list)

    async def test_create_task(self, client):
        resp = await client.post(
            "/api/tasks",
            json={"requirement": "写一个 hello world 程序"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "task_id" in body["data"]
        assert "status" in body["data"]

    async def test_create_and_list_task(self, client):
        # 创建
        resp1 = await client.post(
            "/api/tasks",
            json={"requirement": "实现快速排序算法"},
        )
        assert resp1.status_code == 200
        task_id = resp1.json()["data"]["task_id"]

        # 列出
        resp2 = await client.get("/api/tasks")
        assert resp2.status_code == 200
        tasks = resp2.json()["data"]
        task_ids = [t["task_id"] for t in tasks]
        assert task_id in task_ids

    async def test_get_task_detail(self, client):
        # 创建
        resp1 = await client.post(
            "/api/tasks",
            json={"requirement": "实现二分查找"},
        )
        task_id = resp1.json()["data"]["task_id"]

        # 获取详情
        resp2 = await client.get(f"/api/tasks/{task_id}")
        assert resp2.status_code == 200
        detail = resp2.json()["data"]
        assert detail["task_id"] == task_id
        assert detail["requirement"] == "实现二分查找"

    async def test_get_nonexistent_task(self, client):
        resp = await client.get("/api/tasks/nonexistent-id")
        assert resp.status_code == 404

    async def test_delete_task(self, client):
        # 创建
        resp1 = await client.post(
            "/api/tasks",
            json={"requirement": "待删除的任务"},
        )
        task_id = resp1.json()["data"]["task_id"]

        # 删除
        resp2 = await client.delete(f"/api/tasks/{task_id}")
        assert resp2.status_code == 200

        # 确认已删除
        resp3 = await client.get(f"/api/tasks/{task_id}")
        assert resp3.status_code == 404

    async def test_delete_nonexistent_task(self, client):
        resp = await client.delete("/api/tasks/nonexistent-id")
        assert resp.status_code == 404

    async def test_create_task_empty_requirement(self, client):
        resp = await client.post(
            "/api/tasks",
            json={"requirement": ""},
        )
        # Pydantic 校验 min_length=1 应拒绝空字符串
        assert resp.status_code == 422


# ========================
# 配置管理
# ========================

class TestConfigAPI:
    async def test_get_config(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "llm" in body["data"]

    async def test_config_hides_api_key(self, client):
        resp = await client.get("/api/config")
        body = resp.json()
        llm = body["data"]["llm"]
        # 不应直接暴露 api_key，只应有 api_key_set 布尔值
        assert "api_key" not in llm or llm.get("api_key") is None
        assert "api_key_set" in llm
