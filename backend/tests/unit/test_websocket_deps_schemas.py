"""测试 api/dependencies.py, api/schemas.py, api/websocket/handlers.py

覆盖:
- 全局状态容器的 setter/getter 模式
- Pydantic Schema 验证、默认值、序列化
- WebSocket ConnectionManager 连接管理与广播
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保 src 目录在导入路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from api.dependencies import (
    _state,
    get_agent_registry,
    get_bus,
    get_capability_registry,
    get_context_store,
    get_llm_client,
    get_memory_formation,
    get_memory_buffer,
    get_memory_retriever,
    get_memory_store,
    get_pipeline,
    reload_agent_fn,
    set_agent_registry,
    set_bus,
    set_capability_registry,
    set_context_store,
    set_llm_client,
    set_memory_formation,
    set_memory_buffer,
    set_memory_retriever,
    set_memory_store,
    set_pipeline,
    set_reload_agent_fn,
)
from api.schemas import (
    AgentInfo,
    AgentInvokeRequest,
    APIResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    CustomToolConfigRequest,
    LLMConfigRequest,
    MemoryCreateRequest,
    MemorySearchRequest,
    TaskResponse,
    TaskStatus,
    TaskSubmitRequest,
    ToolsConfigRequest,
    PipelineExecuteRequest,
    PipelineStepSchema,
    PipelineTemplate,
)
from api.websocket import handlers as ws_handlers
from api.websocket.handlers import ConnectionManager


def test_stream_done_event_copies_memory_usage_into_content():
    """SSE done 事件要兼容前端从 content 读取 memories_used 的路径。"""

    from api.main import _attach_stream_memory_usage

    event = {"type": "done", "content": {"response": "ok"}}

    enriched = _attach_stream_memory_usage(event, memories_used=2)

    assert enriched["memories_used"] == 2
    assert enriched["content"]["memories_used"] == 2
    assert event["content"] == {"response": "ok"}


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def reset_app_state():
    """每个测试前后重置全局状态，避免测试间干扰"""
    # 保存原始值
    attrs = [
        "bus", "agent_registry", "current_llm_client",
        "memory_store", "memory_formation", "memory_retriever", "memory_buffer", "reload_agent",
        "context_store", "capability_registry", "pipeline",
    ]
    saved = {a: getattr(_state, a) for a in attrs}
    # 重置为 None
    for a in attrs:
        setattr(_state, a, None)
    yield
    # 恢复
    for a in attrs:
        setattr(_state, a, saved[a])


@pytest.fixture
def manager():
    """返回一个新的 ConnectionManager 实例"""
    return ConnectionManager()


def _mock_ws(*, send_fail=False):
    """创建一个模拟的 WebSocket 对象"""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    if send_fail:
        ws.send_json = AsyncMock(side_effect=RuntimeError("connection closed"))
    else:
        ws.send_json = AsyncMock()
    return ws


# ============================================================
# 1. Dependencies 测试
# ============================================================

class TestDependencies:
    """测试 api/dependencies.py 全局状态容器"""

    def test_initial_state_all_none(self):
        """所有状态初始值为 None"""
        assert get_bus() is None
        assert get_agent_registry() is None
        assert get_llm_client() is None
        assert get_memory_store() is None
        assert get_memory_formation() is None
        assert get_memory_buffer() is None
        assert get_memory_retriever() is None
        assert reload_agent_fn() is None
        assert get_context_store() is None
        assert get_capability_registry() is None
        assert get_pipeline() is None

    def test_set_get_bus(self):
        sentinel = object()
        set_bus(sentinel)
        assert get_bus() is sentinel

    def test_set_get_agent_registry(self):
        sentinel = object()
        set_agent_registry(sentinel)
        assert get_agent_registry() is sentinel

    def test_set_get_pipeline(self):
        sentinel = object()
        set_pipeline(sentinel)
        assert get_pipeline() is sentinel

    def test_set_get_llm_client(self):
        sentinel = object()
        set_llm_client(sentinel)
        assert get_llm_client() is sentinel

    def test_set_get_memory_store(self):
        sentinel = object()
        set_memory_store(sentinel)
        assert get_memory_store() is sentinel

    def test_set_get_memory_formation(self):
        sentinel = object()
        set_memory_formation(sentinel)
        assert get_memory_formation() is sentinel

    def test_set_get_memory_retriever(self):
        sentinel = object()
        set_memory_retriever(sentinel)
        assert get_memory_retriever() is sentinel

    def test_set_get_memory_buffer(self):
        sentinel = object()
        set_memory_buffer(sentinel)
        assert get_memory_buffer() is sentinel

    def test_set_get_reload_agent_fn(self):
        async def dummy():
            pass
        set_reload_agent_fn(dummy)
        assert reload_agent_fn() is dummy

    def test_set_get_context_store(self):
        sentinel = object()
        set_context_store(sentinel)
        assert get_context_store() is sentinel

    def test_set_get_capability_registry(self):
        sentinel = object()
        set_capability_registry(sentinel)
        assert get_capability_registry() is sentinel

    def test_clear_state_by_setting_none(self):
        """设置为 None 可以清除状态"""
        sentinel = object()
        set_bus(sentinel)
        assert get_bus() is sentinel
        set_bus(None)
        assert get_bus() is None

    def test_state_isolation(self):
        """不同依赖项之间互不影响"""
        bus_obj = object()
        registry_obj = object()
        set_bus(bus_obj)
        set_agent_registry(registry_obj)
        assert get_bus() is bus_obj
        assert get_agent_registry() is registry_obj
        # 修改一个不影响另一个
        set_bus(None)
        assert get_bus() is None
        assert get_agent_registry() is registry_obj

    def test_overwrite_state(self):
        """重复设置会覆盖旧值"""
        first = object()
        second = object()
        set_llm_client(first)
        assert get_llm_client() is first
        set_llm_client(second)
        assert get_llm_client() is second


# ============================================================
# 2. Schemas 测试 (28 个)
# ============================================================

class TestAPIResponse:
    def test_ok_response(self):
        r = APIResponse(status="ok", message="success", data={"key": 1})
        assert r.status == "ok"
        assert r.message == "success"
        assert r.data == {"key": 1}

    def test_minimal_response(self):
        r = APIResponse(status="error")
        assert r.message is None
        assert r.data is None

    def test_serialization(self):
        r = APIResponse(status="ok", data=[1, 2, 3])
        d = r.model_dump()
        assert d["status"] == "ok"
        assert d["data"] == [1, 2, 3]
        assert d["message"] is None


class TestTaskStatus:
    def test_all_values(self):
        expected = {"pending", "running", "completed", "failed", "killed"}
        actual = {s.value for s in TaskStatus}
        assert actual == expected

    def test_enum_access(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.FAILED.value == "failed"

    def test_string_comparison(self):
        assert TaskStatus.COMPLETED == "completed"


class TestTaskSubmitRequest:
    def test_valid_request(self):
        r = TaskSubmitRequest(requirement="build a calculator")
        assert r.requirement == "build a calculator"
        assert r.pipeline == "auto"

    def test_custom_pipeline(self):
        r = TaskSubmitRequest(requirement="x", pipeline="plan_code_review")
        assert r.pipeline == "plan_code_review"

    def test_empty_requirement_rejected(self):
        with pytest.raises(Exception):
            TaskSubmitRequest(requirement="")

    def test_missing_requirement_rejected(self):
        with pytest.raises(Exception):
            TaskSubmitRequest()


class TestTaskResponse:
    def test_full_response(self):
        r = TaskResponse(
            task_id="t-1",
            status=TaskStatus.RUNNING,
            requirement="test",
            plan={"steps": []},
            code={"files": []},
            review=None,
            created_at="2026-03-28T00:00:00",
            updated_at="2026-03-28T00:00:00",
        )
        assert r.task_id == "t-1"
        assert r.status == TaskStatus.RUNNING
        assert r.plan == {"steps": []}
        assert r.review is None

    def test_optional_fields_default_none(self):
        r = TaskResponse(
            task_id="t-2",
            status=TaskStatus.PENDING,
            requirement="hello",
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        assert r.plan is None
        assert r.code is None
        assert r.review is None


class TestAgentInfo:
    def test_valid_agent_info(self):
        a = AgentInfo(name="coder", status="idle", capabilities=["python", "js"])
        assert a.name == "coder"
        assert a.description == ""

    def test_with_description(self):
        a = AgentInfo(name="planner", status="busy", capabilities=[], description="Plans tasks")
        assert a.description == "Plans tasks"


class TestAgentInvokeRequest:
    def test_default_empty_dict(self):
        r = AgentInvokeRequest()
        assert r.data == {}

    def test_with_data(self):
        r = AgentInvokeRequest(data={"code": "print(1)"})
        assert r.data["code"] == "print(1)"

    def test_legacy_flat_payload_is_preserved_as_data(self):
        r = AgentInvokeRequest(input="hello", session_id="s1")
        assert r.data == {"input": "hello", "session_id": "s1"}


class TestPipelineExecuteRequest:
    def test_defaults(self):
        r = PipelineExecuteRequest()
        assert r.pipeline_type == "plan_code_review"
        assert r.template_name is None
        assert r.requirement == ""
        assert r.input is None
        assert r.options == {}

    def test_custom_values(self):
        r = PipelineExecuteRequest(
            pipeline_type="custom",
            template_name="full_pipeline",
            requirement="build API",
            input="alt input",
            options={"retry": True},
        )
        assert r.template_name == "full_pipeline"
        assert r.options["retry"] is True


class TestPipelineStepSchema:
    def test_accepts_timeout(self):
        step = PipelineStepSchema(name="review", agent="reviewer", timeout=2.5)
        assert step.timeout == 2.5

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(Exception):
            PipelineStepSchema(name="review", agent="reviewer", timeout=0)


class TestPipelineTemplate:
    def test_valid_template(self):
        t = PipelineTemplate(name="basic", description="A basic flow", steps=["plan", "code"])
        assert t.name == "basic"
        assert len(t.steps) == 2


class TestLLMConfigRequest:
    def test_minimal(self):
        c = LLMConfigRequest(provider="openai", model="gpt-4")
        assert c.api_key == ""
        assert c.base_url == ""
        assert c.temperature is None
        assert c.top_p is None
        assert c.max_tokens is None
        assert c.stop_sequences == []
        assert c.openai == {}
        assert c.anthropic == {}

    def test_full(self):
        c = LLMConfigRequest(
            provider="anthropic",
            api_key="sk-xxx",
            model="claude-3",
            base_url="https://api.example.com",
            temperature=0.2,
            top_p=0.8,
            max_tokens=8192,
            stop_sequences=["STOP"],
            anthropic={"top_k": 40},
        )
        assert c.provider == "anthropic"
        assert c.api_key == "sk-xxx"
        assert c.temperature == 0.2
        assert c.top_p == 0.8
        assert c.max_tokens == 8192
        assert c.stop_sequences == ["STOP"]
        assert c.anthropic["top_k"] == 40


class TestToolsConfigRequest:
    def test_defaults(self):
        config = ToolsConfigRequest()
        assert config.web_search.provider == "duckduckgo"
        assert config.web_search.api_key == ""
        assert config.custom == {}

    def test_custom_tool_config(self):
        config = ToolsConfigRequest(
            custom={
                "notion_search": CustomToolConfigRequest(
                    base_url="https://api.notion.com",
                    api_key="secret",
                    extra={"version": "2022-06-28"},
                )
            }
        )
        assert config.custom["notion_search"].enabled is True
        assert config.custom["notion_search"].api_key == "secret"
        assert config.custom["notion_search"].extra["version"] == "2022-06-28"


class TestConfigUpdateRequest:
    def test_valid(self):
        llm = LLMConfigRequest(provider="openai", model="gpt-4")
        r = ConfigUpdateRequest(llm=llm)
        assert r.llm.provider == "openai"


class TestConfigResponse:
    def test_valid(self):
        r = ConfigResponse(llm={"provider": "openai", "model": "gpt-4"})
        assert r.llm["provider"] == "openai"


class TestMemoryCreateRequest:
    def test_valid_with_defaults(self):
        r = MemoryCreateRequest(content="some fact")
        assert r.type == "semantic"
        assert r.importance == 0.5
        assert r.metadata == {}

    def test_custom_values(self):
        r = MemoryCreateRequest(
            content="important",
            type="episodic",
            importance=0.9,
            metadata={"source": "user"},
        )
        assert r.type == "episodic"
        assert r.importance == 0.9

    def test_empty_content_rejected(self):
        with pytest.raises(Exception):
            MemoryCreateRequest(content="")

    def test_importance_below_zero_rejected(self):
        with pytest.raises(Exception):
            MemoryCreateRequest(content="x", importance=-0.1)

    def test_importance_above_one_rejected(self):
        with pytest.raises(Exception):
            MemoryCreateRequest(content="x", importance=1.1)

    def test_importance_boundary_zero(self):
        r = MemoryCreateRequest(content="x", importance=0.0)
        assert r.importance == 0.0

    def test_importance_boundary_one(self):
        r = MemoryCreateRequest(content="x", importance=1.0)
        assert r.importance == 1.0


class TestMemorySearchRequest:
    def test_valid_with_defaults(self):
        r = MemorySearchRequest(query="find something")
        assert r.max_results == 5

    def test_custom_max_results(self):
        r = MemorySearchRequest(query="q", max_results=20)
        assert r.max_results == 20

    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            MemorySearchRequest(query="")

    def test_max_results_below_one_rejected(self):
        with pytest.raises(Exception):
            MemorySearchRequest(query="q", max_results=0)

    def test_max_results_above_fifty_rejected(self):
        with pytest.raises(Exception):
            MemorySearchRequest(query="q", max_results=51)

    def test_max_results_boundary_one(self):
        r = MemorySearchRequest(query="q", max_results=1)
        assert r.max_results == 1

    def test_max_results_boundary_fifty(self):
        r = MemorySearchRequest(query="q", max_results=50)
        assert r.max_results == 50


# ============================================================
# 3. WebSocket ConnectionManager 测试 (13 个)
# ============================================================

class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_initial_state(self, manager):
        assert manager.active_count == 0
        assert manager.connections == []

    @pytest.mark.asyncio
    async def test_connect_adds_to_list(self, manager):
        ws = _mock_ws()
        await manager.connect(ws)
        assert manager.active_count == 1
        assert ws in manager.connections
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_multiple(self, manager):
        ws1, ws2, ws3 = _mock_ws(), _mock_ws(), _mock_ws()
        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.connect(ws3)
        assert manager.active_count == 3

    @pytest.mark.asyncio
    async def test_disconnect_removes(self, manager):
        ws = _mock_ws()
        await manager.connect(ws)
        manager.disconnect(ws)
        assert manager.active_count == 0
        assert ws not in manager.connections

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_safe(self, manager):
        ws = _mock_ws()
        manager.disconnect(ws)  # 不在列表中，不应报错
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self, manager):
        ws1, ws2 = _mock_ws(), _mock_ws()
        await manager.connect(ws1)
        await manager.connect(ws2)
        msg = {"type": "test", "data": "hello"}
        await manager.broadcast(msg)
        ws1.send_json.assert_awaited_once_with(msg)
        ws2.send_json.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self, manager):
        ws_ok = _mock_ws()
        ws_dead = _mock_ws(send_fail=True)
        await manager.connect(ws_ok)
        await manager.connect(ws_dead)
        assert manager.active_count == 2
        await manager.broadcast({"type": "ping"})
        # 死连接应被清理
        assert manager.active_count == 1
        assert ws_ok in manager.connections
        assert ws_dead not in manager.connections

    @pytest.mark.asyncio
    async def test_broadcast_empty_connections(self, manager):
        # 没有连接时广播不应报错
        await manager.broadcast({"type": "noop"})
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_send_to_specific(self, manager):
        ws = _mock_ws()
        await manager.connect(ws)
        msg = {"type": "direct", "data": "hi"}
        await manager.send_to(ws, msg)
        ws.send_json.assert_awaited_with(msg)

    @pytest.mark.asyncio
    async def test_send_to_dead_connection_disconnects(self, manager):
        ws = _mock_ws(send_fail=True)
        await manager.connect(ws)
        assert manager.active_count == 1
        await manager.send_to(ws, {"type": "test"})
        # 发送失败应自动断开
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_connections_property_returns_copy(self, manager):
        ws = _mock_ws()
        await manager.connect(ws)
        conns = manager.connections
        conns.clear()  # 修改副本不应影响原始列表
        assert manager.active_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_partial_failure(self, manager):
        """部分连接失败时，正常连接仍能收到消息"""
        ws1 = _mock_ws()
        ws2 = _mock_ws(send_fail=True)
        ws3 = _mock_ws()
        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.connect(ws3)
        msg = {"type": "mixed"}
        await manager.broadcast(msg)
        ws1.send_json.assert_awaited_once_with(msg)
        ws3.send_json.assert_awaited_once_with(msg)
        assert manager.active_count == 2

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self, manager):
        """多次断开同一连接不应报错"""
        ws = _mock_ws()
        await manager.connect(ws)
        manager.disconnect(ws)
        manager.disconnect(ws)
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_user_message_forwards_session_id_to_reflection(self, monkeypatch):
        """WebSocket 聊天反思应使用前端传入的 session_id。"""

        class FakeCapabilityRegistry:
            def __contains__(self, name):
                return name == "assistant"

            async def execute(self, name, **kwargs):
                return {"response": "ok"}

        ws = _mock_ws()
        scheduled = []
        monkeypatch.setattr(ws_handlers, "manager", ConnectionManager())
        monkeypatch.setattr(
            ws_handlers,
            "get_capability_registry",
            lambda: FakeCapabilityRegistry(),
        )
        monkeypatch.setattr(
            ws_handlers,
            "build_memory_context",
            AsyncMock(return_value=("", 0)),
        )
        monkeypatch.setattr(
            ws_handlers,
            "schedule_memory_reflection",
            lambda **kwargs: scheduled.append(kwargs),
        )

        await ws_handlers._handle_user_message(
            ws,
            {"message": "hello", "session_id": "chat-1"},
        )

        assert len(scheduled) == 1
        assert scheduled[0]["session_id"] == "chat-1"
