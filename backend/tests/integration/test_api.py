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
import yaml
from httpx import AsyncClient, ASGITransport

from core.bus import SimpleBus
from core.capability import CapabilityRegistry, DynamicToolCapability
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
    set_capability_registry,
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
        chat_sessions_router,
        pipelines_router,
        memory_router,
        config_router,
        evolution_router,
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
    test_app.include_router(pipelines_router)
    test_app.include_router(memory_router)
    test_app.include_router(config_router)
    test_app.include_router(evolution_router)
    test_app.include_router(chat_sessions_router)

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
    cap_registry = CapabilityRegistry()
    cap_registry.register_native(
        DynamicToolCapability(
            name="requirement_checklist",
            mode="checklist",
            config={"required_terms": ["目标"]},
        )
    )

    # 创建一个 mock Pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value={"status": "completed"})

    set_bus(bus)
    set_agent_registry(registry)
    set_pipeline(mock_pipeline)
    set_capability_registry(cap_registry)
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
        "cap_registry": cap_registry,
    }

    # 清理
    await bus.stop()
    set_bus(None)
    set_agent_registry(None)
    set_pipeline(None)
    set_capability_registry(None)
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


@pytest.fixture
def chat_sessions_file(tmp_path, monkeypatch):
    """Use an isolated chat history file for chat session API tests."""

    path = tmp_path / "chat_sessions.json"
    monkeypatch.setenv("CHAT_SESSIONS_FILE", str(path))
    return path


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
# 聊天分页 / 历史会话
# ========================

class TestChatSessionsAPI:
    async def test_create_and_list_chat_sessions(self, client, chat_sessions_file):
        resp = await client.post("/api/chat-sessions", json={"title": "第一页"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["title"] == "第一页"
        assert body["data"]["messages"] == []
        assert chat_sessions_file.exists()

        list_resp = await client.get("/api/chat-sessions")
        assert list_resp.status_code == 200
        sessions = list_resp.json()["data"]
        assert len(sessions) == 1
        assert sessions[0]["title"] == "第一页"
        assert sessions[0]["message_count"] == 0

    async def test_add_message_updates_session_title(self, client, chat_sessions_file):
        create_resp = await client.post("/api/chat-sessions", json={})
        session_id = create_resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/chat-sessions/{session_id}/messages",
            json={
                "id": "msg-1",
                "type": "user",
                "content": "帮我设计一个私人助理 Agent",
                "timestamp": "2026-04-24T00:00:00+00:00",
                "elapsedMs": 123.4,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "total_tokens": 30,
                },
            },
        )
        assert resp.status_code == 200
        session = resp.json()["data"]
        assert session["title"] == "帮我设计一个私人助理 Agent"
        assert session["messages"][0]["id"] == "msg-1"
        assert session["messages"][0]["elapsedMs"] == 123.4
        assert session["messages"][0]["usage"]["total_tokens"] == 30
        assert chat_sessions_file.exists()

    async def test_multiple_chat_sessions_are_isolated(self, client, chat_sessions_file):
        first = (await client.post("/api/chat-sessions", json={"title": "A"})).json()["data"]
        second = (await client.post("/api/chat-sessions", json={"title": "B"})).json()["data"]

        await client.post(
            f"/api/chat-sessions/{first['id']}/messages",
            json={"type": "user", "content": "first only"},
        )
        await client.post(
            f"/api/chat-sessions/{second['id']}/messages",
            json={"type": "user", "content": "second only"},
        )

        first_resp = await client.get(f"/api/chat-sessions/{first['id']}")
        second_resp = await client.get(f"/api/chat-sessions/{second['id']}")

        assert first_resp.status_code == 200
        assert second_resp.status_code == 200
        assert first_resp.json()["data"]["messages"][0]["content"] == "first only"
        assert second_resp.json()["data"]["messages"][0]["content"] == "second only"
        assert chat_sessions_file.exists()

    async def test_delete_chat_session(self, client, chat_sessions_file):
        created = (await client.post("/api/chat-sessions", json={})).json()["data"]

        delete_resp = await client.delete(f"/api/chat-sessions/{created['id']}")
        assert delete_resp.status_code == 200

        get_resp = await client.get(f"/api/chat-sessions/{created['id']}")
        assert get_resp.status_code == 404
        assert chat_sessions_file.exists()


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

        # v2 Phase B：DELETE 请求 cancel；任务记录保留并标记 killed
        resp2 = await client.delete(f"/api/tasks/{task_id}")
        assert resp2.status_code == 200

        # 任务详情仍可查；状态最终会变为 killed（也允许还在过渡到 killed 的时间窗）
        resp3 = await client.get(f"/api/tasks/{task_id}")
        assert resp3.status_code == 200
        assert resp3.json()["data"]["status"] in {"killed", "running", "failed"}

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

    async def test_update_config_preserves_tool_secrets_and_unknown_tools(
        self,
        client,
        tmp_path,
        monkeypatch,
    ):
        import api.routes.config as config_route
        import core.config as core_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-old",
                        "api_key": "old-llm-key",
                        "base_url": "https://old-llm.example/v1",
                        "temperature": 0.2,
                        "max_tokens": 1024,
                    },
                    "tools": {
                        "web_search": {
                            "provider": "brave",
                            "api_key": "old-search-key",
                            "base_url": "https://old-search.example",
                            "max_results": 3,
                            "timeout": 4,
                        },
                        "custom": {
                        "ticket_api": {
                            "enabled": True,
                            "base_url": "https://ticket.example",
                            "api_key": "old-ticket-key",
                            "extra": {"project": "demo", "token": "hidden"},
                        }
                        },
                        "future_tool": {
                            "base_url": "https://future.example",
                            "api_key": "keep-me",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(config_route, "_runtime_config_path", lambda: config_file)
        monkeypatch.setattr(core_config, "_default_runtime_config_path", lambda: config_file)

        resp = await client.post(
            "/api/config",
            json={
                "llm": {
                    "provider": "openai",
                    "model": "gpt-5.4",
                    "api_key": "",
                    "base_url": "https://new-llm.example/v1",
                    "temperature": 0.4,
                    "max_tokens": 4096,
                },
                "tools": {
                    "web_search": {
                        "provider": "brave",
                        "base_url": "https://new-search.example",
                        "api_key": "",
                        "max_results": 5,
                        "timeout": 8,
                    },
                    "web_fetch": {"timeout": 9, "max_chars": 5000},
                    "file": {"workspace_root": ""},
                    "shell": {"enabled": False, "timeout": 30},
                    "custom": {
                        "ticket_api": {
                            "enabled": True,
                            "base_url": "https://ticket.example",
                            "api_key": "",
                            "extra": {"project": "demo", "region": "sg", "token": "hidden"},
                        }
                    },
                },
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert saved["llm"]["api_key"] == "old-llm-key"
        assert saved["llm"]["model"] == "gpt-5.4"
        assert saved["tools"]["web_search"]["api_key"] == "old-search-key"
        assert saved["tools"]["custom"]["ticket_api"]["api_key"] == "old-ticket-key"
        assert saved["tools"]["future_tool"]["api_key"] == "keep-me"

        get_resp = await client.get("/api/config")
        data = get_resp.json()["data"]
        assert "api_key" not in data["llm"]
        assert data["tools"]["web_search"]["api_key_set"] is True
        assert data["tools"]["custom"]["ticket_api"]["api_key_set"] is True
        assert "api_key" not in data["tools"]["custom"]["ticket_api"]
        assert "token" not in data["tools"]["custom"]["ticket_api"]["extra"]


# ========================
# 进化能力图
# ========================


class TestEvolutionAPI:
    async def test_evolution_graph(self, client):
        resp = await client.get("/api/evolution/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        data = body["data"]
        assert "summary" in data
        assert data["summary"]["dynamic_tools"] == 1
        node_ids = {node["id"] for node in data["nodes"]}
        assert "requirement_checklist" in node_ids

    async def test_tool_prompts_schema_is_listed_readonly(self, client):
        resp = await client.get("/api/evolution/tool-prompts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        tools = body["data"]
        requirement_tool = next(
            item for item in tools if item["name"] == "requirement_checklist"
        )
        assert requirement_tool["prompt"]
        assert requirement_tool["schema"]["type"] == "object"
