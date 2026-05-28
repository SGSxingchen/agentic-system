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
import asyncio
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
from core.capability.base import CapabilityBase, CapabilitySchema
from core.memory import (
    MemoryFormation,
    MemoryRetriever,
    InMemoryStore,
    MemoryType,
)
from core.agent import AgentRegistry


class EchoAgentCapability(CapabilityBase):
    calls = []

    @property
    def name(self):
        return "assistant"

    @property
    def description(self):
        return "test assistant"

    def get_schema(self):
        return CapabilitySchema(name=self.name, description=self.description)

    async def execute(self, **kwargs):
        self.__class__.calls.append(dict(kwargs))
        return {"response": kwargs.get("message"), "workspace_id": kwargs.get("workspace_id")}


from api.dependencies import (
    set_bus,
    set_agent_registry,
    set_memory_store,
    set_memory_formation,
    set_memory_retriever,
    set_reload_agent_fn,
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
        runs_router,
        agents_router,
        chat_sessions_router,
        memory_router,
        config_router,
        evolution_router,
        personas_router,
        artifacts_router,
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
    test_app.include_router(runs_router)
    test_app.include_router(agents_router)
    test_app.include_router(memory_router)
    test_app.include_router(config_router)
    test_app.include_router(evolution_router)
    test_app.include_router(personas_router)
    test_app.include_router(chat_sessions_router)
    test_app.include_router(artifacts_router)

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
    EchoAgentCapability.calls = []
    cap_registry.register_native(EchoAgentCapability())
    cap_registry.register_native(
        DynamicToolCapability(
            name="requirement_checklist",
            mode="checklist",
            config={"required_terms": ["目标"]},
        )
    )

    set_bus(bus)
    set_agent_registry(registry)
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
        "cap_registry": cap_registry,
    }

    # 清理
    await bus.stop()
    set_bus(None)
    set_agent_registry(None)
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
def artifact_store_dir(tmp_path, monkeypatch):
    path = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACT_STORE_DIR", str(path))
    return path


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

    async def test_capabilities_list_route_is_not_shadowed(self, client):
        resp = await client.get("/api/agents/capabilities/list")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        names = {item["name"] for item in body["data"]}
        assert "assistant" in names
        assert "requirement_checklist" in names

    async def test_delete_protected_agent_no_longer_blocked(self, client, monkeypatch):
        """A22 — REST 路由层不再硬保护内置 Agent；通过 stub yaml 验证 DELETE 走通。"""

        from copy import deepcopy
        from api.routes import agents as agent_routes

        state = {
            "data": {
                "agents": [
                    {"name": "assistant", "description": "原描述"},
                ]
            },
            "saved": None,
        }

        def fake_load(_name):
            return deepcopy(state["data"])

        async def fake_save(data, previous_data):
            state["saved"] = deepcopy(data)
            state["data"] = deepcopy(data)

        monkeypatch.setattr(agent_routes, "load_single_yaml", fake_load)
        monkeypatch.setattr(agent_routes, "_save_config_and_reload", fake_save)

        resp = await client.delete("/api/agents/assistant")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok", f"DELETE 应被允许：{body.get('message')}"
        assert state["saved"] is not None
        assert "assistant" not in [a.get("name") for a in state["saved"]["agents"]]


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
        assert body["data"]
        assert "retrieval" in body["data"][0]
        assert "score" in body["data"][0]["retrieval"]
        assert "breakdown" in body["data"][0]["retrieval"]

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
                "agent_name": "assistant",
                "error": "example_error",
            },
        )
        assert resp.status_code == 200
        session = resp.json()["data"]
        assert session["title"] == "帮我设计一个私人助理 Agent"
        assert session["messages"][0]["id"] == "msg-1"
        assert session["messages"][0]["elapsedMs"] == 123.4
        assert session["messages"][0]["usage"]["total_tokens"] == 30
        assert session["messages"][0]["agent_name"] == "assistant"
        assert session["messages"][0]["error"] == "example_error"
        assert chat_sessions_file.exists()

        list_resp = await client.get("/api/chat-sessions")
        assert list_resp.json()["data"][0]["last_message"] == "帮我设计一个私人助理 Agent"

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

    async def test_chat_session_workspace_binding_can_be_created_and_updated(self, client, chat_sessions_file):
        created = (
            await client.post(
                "/api/chat-sessions",
                json={"title": "workspace bound", "workspace_id": "project-a"},
            )
        ).json()["data"]

        assert created["workspace_id"] == "project-a"

        resp = await client.put(
            f"/api/chat-sessions/{created['id']}",
            json={"workspace_id": "project-b"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["workspace_id"] == "project-b"


# ========================
# 任务管理
# ========================

class TestRunsAPI:
    async def _wait_for_run(self, client, run_id: str) -> dict:
        for _ in range(50):
            resp = await client.get(f"/api/runs/{run_id}")
            data = resp.json()["data"]
            if data["status"] in {"completed", "failed", "killed"}:
                return data
            await asyncio.sleep(0.01)
        return data

    async def test_list_runs(self, client):
        resp = await client.get("/api/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert isinstance(body["data"], list)

    async def test_create_run_returns_agent_run(self, client):
        resp = await client.post(
            "/api/runs",
            json={
                "goal": "做一个并发运行模型",
                "agent_name": "assistant",
                "workspace_id": "test-ws",
                "mode": "continuous",
                "max_iterations": 77,
                "completion_criteria": "运行卡片展示持续工作语义",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["type"] == "agent_run"
        assert body["data"]["agent_name"] == "assistant"
        assert body["data"]["workspace_id"] == "test-ws"
        assert body["data"]["mode"] == "continuous"
        assert body["data"]["max_iterations"] == 77
        assert body["data"]["completion_criteria"] == "运行卡片展示持续工作语义"

    async def test_control_run_pause_and_resume(self, client):
        resp = await client.post(
            "/api/runs",
            json={"goal": "持续推进目标", "agent_name": "assistant"},
        )
        assert resp.status_code == 200
        run_id = resp.json()["data"]["run_id"]

        pause_resp = await client.post(f"/api/runs/{run_id}/control", json={"action": "pause"})
        assert pause_resp.status_code == 200
        assert pause_resp.json()["data"]["status"] == "paused"

        resume_resp = await client.post(f"/api/runs/{run_id}/control", json={"action": "resume"})
        assert resume_resp.status_code == 200
        assert resume_resp.json()["data"]["status"] == "running"

    async def test_create_run_auto_memory_injects_and_reflects(self, client, monkeypatch):
        from api.routes import tasks as tasks_route

        reflected = []
        monkeypatch.setattr(
            tasks_route,
            "build_memory_context",
            AsyncMock(return_value=("- remembered run context", 1)),
        )
        monkeypatch.setattr(
            tasks_route,
            "schedule_memory_reflection",
            lambda **kwargs: reflected.append(kwargs),
        )

        resp = await client.post(
            "/api/runs",
            json={
                "goal": "实现运行记忆",
                "agent_name": "assistant",
                "input": {"context": "需要召回长期偏好"},
                "auto_memory": True,
            },
        )
        assert resp.status_code == 200
        run_id = resp.json()["data"]["run_id"]

        data = await self._wait_for_run(client, run_id)

        assert data["status"] == "completed"
        assert tasks_route.build_memory_context.await_count == 1
        assert EchoAgentCapability.calls[-1]["memory_context"] == "- remembered run context"
        assert EchoAgentCapability.calls[-1]["auto_memory"] is True
        assert reflected
        assert reflected[-1]["source"] == "agent_run:assistant"

        events_resp = await client.get(f"/api/runs/{run_id}/events")
        events = [item["payload"] for item in events_resp.json()["data"]["events"]]
        started = next(item for item in events if item.get("kind") == "agent_run" and "workspace_root" in item)
        assert started["auto_memory"] is True
        assert started["memory_count"] == 1

    async def test_create_run_auto_memory_false_skips_recall_and_reflection(self, client, monkeypatch):
        from api.routes import tasks as tasks_route

        reflected = []
        monkeypatch.setattr(
            tasks_route,
            "build_memory_context",
            AsyncMock(return_value=("- should not be used", 1)),
        )
        monkeypatch.setattr(
            tasks_route,
            "schedule_memory_reflection",
            lambda **kwargs: reflected.append(kwargs),
        )

        resp = await client.post(
            "/api/runs",
            json={
                "goal": "禁用运行记忆",
                "agent_name": "assistant",
                "input": {"memory_context": "caller supplied context should be stripped"},
                "auto_memory": False,
            },
        )
        assert resp.status_code == 200
        run_id = resp.json()["data"]["run_id"]

        data = await self._wait_for_run(client, run_id)

        assert data["status"] == "completed"
        assert tasks_route.build_memory_context.await_count == 0
        assert "memory_context" not in EchoAgentCapability.calls[-1]
        assert EchoAgentCapability.calls[-1]["auto_memory"] is False
        assert reflected == []

    async def test_create_run_uses_agent_default_workspace_root_fallback(self, client, monkeypatch):
        from api.routes import tasks as tasks_route

        default_root = "./workspace/agent-default-test"
        monkeypatch.setattr(
            tasks_route,
            "load_single_yaml",
            lambda name: {
                "agents": [
                    {
                        "name": "assistant",
                        "default_workspace_root": default_root,
                    }
                ]
            },
        )

        resp = await client.post(
            "/api/runs",
            json={"goal": "使用 Agent 默认工作区根", "agent_name": "assistant"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        run_id = body["data"]["run_id"]
        assert body["data"]["workspace_id"] == "agent-assistant"

        data = await self._wait_for_run(client, run_id)
        expected_root = (Path(__file__).resolve().parents[3] / default_root).resolve()

        assert data["status"] == "completed"
        assert expected_root.is_dir()
        assert EchoAgentCapability.calls[-1]["workspace_id"] == "agent-assistant"
        assert EchoAgentCapability.calls[-1]["workspace_root"] == str(expected_root)
        assert EchoAgentCapability.calls[-1]["_trusted_workspace_root"] == str(expected_root)

    async def test_get_run_memory_context(self, client, setup_deps):
        await setup_deps["formation"].create_memory(
            content="用户偏好：前端要像目标工作台，而不是普通工具箱。",
            memory_type=MemoryType.SEMANTIC,
            importance=0.9,
            metadata={"source": "test"},
        )
        resp = await client.post(
            "/api/runs",
            json={"goal": "优化目标工作台 UI", "agent_name": "assistant"},
        )
        assert resp.status_code == 200
        run_id = resp.json()["data"]["run_id"]

        memory_resp = await client.get(f"/api/runs/{run_id}/memory-context")
        assert memory_resp.status_code == 200
        body = memory_resp.json()
        assert body["status"] == "ok"
        assert body["data"]["run_id"] == run_id
        assert body["data"]["query"] == "优化目标工作台 UI"
        assert body["data"]["memories"]
        assert "目标工作台" in body["data"]["memories"][0]["content"]

    async def test_create_run_unknown_agent_returns_error(self, client):
        resp = await client.post(
            "/api/runs",
            json={"goal": "做一个并发运行模型", "agent_name": "missing-agent"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"

    async def test_task_auto_compat_creates_agent_run_record(self, client):
        resp = await client.post("/api/tasks", json={"requirement": "兼容任务提交"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["type"] == "agent_run"
        assert body["data"]["run_id"] == body["data"]["task_id"]


class TestTasksAPI:
    async def test_pipeline_api_is_removed(self, client):
        resp = await client.get("/api/pipelines/templates")
        assert resp.status_code == 404

        resp = await client.post(
            "/api/pipelines/execute",
            json={"requirement": "不应存在", "template_name": "full_pipeline"},
        )
        assert resp.status_code == 404

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
        assert resp3.json()["data"]["status"] in {"killed", "running", "failed", "completed"}

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
# Artifact / 前端附件
# ========================

class TestArtifactsAPI:
    async def test_create_preview_and_download_text_artifact(self, client, artifact_store_dir):
        resp = await client.post(
            "/api/artifacts",
            json={
                "kind": "html",
                "title": "Demo Artifact",
                "content": "<h1>Hello Artifact</h1>",
                "mime_type": "text/html",
                "filename": "demo.html",
                "session_id": "s1",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        artifact = body["data"]
        assert artifact["title"] == "Demo Artifact"
        assert artifact["download_url"].endswith("/download")
        assert (artifact_store_dir / "artifacts.json").exists()

        content_resp = await client.get(f"/api/artifacts/{artifact['id']}/content")
        assert content_resp.status_code == 200
        assert "Hello Artifact" in content_resp.json()["data"]["content"]

        download_resp = await client.get(f"/api/artifacts/{artifact['id']}/download")
        assert download_resp.status_code == 200
        assert download_resp.text == "<h1>Hello Artifact</h1>"

    async def test_list_artifacts_can_filter_by_session(self, client, artifact_store_dir):
        await client.post("/api/artifacts", json={"kind": "text", "title": "A", "content": "a", "session_id": "s1"})
        await client.post("/api/artifacts", json={"kind": "text", "title": "B", "content": "b", "session_id": "s2"})
        resp = await client.get("/api/artifacts?session_id=s1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["title"] == "A"


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

    async def test_update_config_preserves_masked_key_and_normalizes_or_clears_base_url(
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
                        "api_key": "real-key",
                        "base_url": "https://old.example/v1",
                        "temperature": 0.2,
                        "max_tokens": 1024,
                    }
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
                    "api_key": "********",
                    "base_url": "https://proxy.example.com/openai/v1/models",
                    "temperature": 0.4,
                    "max_tokens": 4096,
                }
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert saved["llm"]["api_key"] == "real-key"
        assert saved["llm"]["base_url"] == "https://proxy.example.com/openai/v1"

        clear_resp = await client.post(
            "/api/config",
            json={
                "llm": {
                    "provider": "openai",
                    "model": "gpt-5.4",
                    "api_key": "",
                    "base_url": "",
                    "temperature": 0.4,
                    "max_tokens": 4096,
                }
            },
        )

        assert clear_resp.status_code == 200
        assert clear_resp.json()["status"] == "ok"
        saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert saved["llm"]["api_key"] == "real-key"
        assert saved["llm"]["base_url"] == ""

    async def test_model_list_uses_saved_key_and_normalizes_openai_base_url(
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
                        "api_key": "saved-key",
                        "base_url": "https://saved.example/v1",
                        "model": "gpt-old",
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(config_route, "_runtime_config_path", lambda: config_file)
        monkeypatch.setattr(core_config, "_default_runtime_config_path", lambda: config_file)
        for env_name in (
            "LLM_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_API_KEY",
        ):
            monkeypatch.delenv(env_name, raising=False)

        fetch_mock = AsyncMock(return_value=[{"id": "gpt-test"}])
        monkeypatch.setattr(config_route, "_fetch_openai_models", fetch_mock)

        resp = await client.post(
            "/api/config/models",
            json={
                "provider": "openai",
                "api_key": "••••••••",
                "base_url": "https://proxy.example.com/api/v1/chat/completions",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["models"] == [{"id": "gpt-test"}]
        fetch_mock.assert_awaited_once_with(
            "saved-key",
            "https://proxy.example.com/api/v1",
        )

    async def test_model_list_failure_returns_readable_error(
        self,
        client,
        tmp_path,
        monkeypatch,
    ):
        import api.routes.config as config_route
        import core.config as core_config

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"llm": {"provider": "openai", "api_key": "saved-key"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(config_route, "_runtime_config_path", lambda: config_file)
        monkeypatch.setattr(core_config, "_default_runtime_config_path", lambda: config_file)
        monkeypatch.setattr(
            config_route,
            "_fetch_openai_models",
            AsyncMock(side_effect=RuntimeError("connection refused by model provider")),
        )

        resp = await client.post("/api/config/models", json={"provider": "openai"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "connection refused" in body["message"]
        assert body["data"]["models"] == []


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

    async def test_evolution_system_status(self, client):
        resp = await client.get("/api/evolution/system-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        data = body["data"]
        assert data["overview"]["agent_count"] >= 0
        component_ids = {component["id"] for component in data["components"]}
        assert {"agents", "tools", "memory", "runtime", "evolution_loop"}.issubset(component_ids)
        assert data["graph"]["summary"]["dynamic_tools"] == 1

    async def test_evolution_command(self, client):
        resp = await client.post(
            "/api/evolution/command",
            json={"goal": "增强 memory reflection 的可观测性"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "系统级进化任务" in body["data"]["command"]
        assert "memory" in body["data"]["target_components"]
