"""End-to-end pipeline tests for the Phase 2 chatroom orchestrator.

These tests use FastAPI's TestClient + ASGITransport to drive the chatroom
routes the way a real client would, and inject scripted streaming agents into
``CapabilityRegistry`` so the relay/streaming logic can be exercised without a
live LLM.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# 与其他集成测试一致：在 import 时把 backend/src 注入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.bus import SimpleBus
from core.capability import CapabilityRegistry
from core.capability.base import CapabilityBase, CapabilitySchema
from core.task import TaskRegistry, TaskStatus

from api.dependencies import (
    set_bus,
    set_capability_registry,
    set_task_registry,
    set_reload_agent_fn,
)


# ─── Mock streaming capability ─────────────────────────────


class StreamingCap(CapabilityBase):
    def __init__(
        self,
        name: str,
        events: List[Dict[str, Any]],
    ) -> None:
        super().__init__()
        self._name = name
        self._events = events
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def description(self) -> str:  # type: ignore[override]
        return f"echo {self._name}"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self._name, description=self.description)

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        return {"response": f"finished {self._name}"}

    async def execute_stream(self, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
        self.calls.append(dict(kwargs))
        for event in self._events:
            yield dict(event)


def _build_test_app() -> FastAPI:
    @asynccontextmanager
    async def _noop(_: FastAPI):
        yield

    app = FastAPI(lifespan=_noop)
    from api.routes import chatrooms_router

    app.include_router(chatrooms_router)
    return app


@pytest.fixture
def isolated_chatrooms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHATROOMS_DIR", str(tmp_path / "rooms"))


@pytest.fixture
async def deps(isolated_chatrooms):
    bus = SimpleBus()
    await bus.start()
    cap_registry = CapabilityRegistry()
    task_registry = TaskRegistry()

    set_bus(bus)
    set_capability_registry(cap_registry)
    set_task_registry(task_registry)
    set_reload_agent_fn(AsyncMock())

    yield {
        "bus": bus,
        "cap_registry": cap_registry,
        "task_registry": task_registry,
    }

    await bus.stop()
    set_bus(None)
    set_capability_registry(None)
    set_task_registry(None)
    set_reload_agent_fn(None)


@pytest.fixture
async def client(deps):
    app = _build_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Helpers ───────────────────────────────────────────────


async def _wait_for(condition, *, timeout: float = 2.0, step: float = 0.05) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(step)
    return False


# ─── Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_message_with_mention_dispatches_speaker(client, deps):
    deps["cap_registry"].register_native(
        StreamingCap(
            "planner",
            [
                {"type": "thinking", "content": "thinking..."},
                {"type": "done", "content": {"response": "got it"}},
            ],
        )
    )

    create = await client.post(
        "/api/chatrooms",
        json={
            "title": "毕设组",
            "topic": "phase2",
            "members": ["planner"],
        },
    )
    assert create.status_code == 200
    room_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/chatrooms/{room_id}/messages",
        json={"content": "嗨 @planner，开始吧"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["mentions"] == ["planner"]
    assert len(body["dispatched_tasks"]) == 1
    ticket = body["dispatched_tasks"][0]
    assert ticket["task_id"]

    # 等后台 task 终态
    task_registry: TaskRegistry = deps["task_registry"]
    completed = await _wait_for(
        lambda: task_registry.get(ticket["task_id"]) is not None
        and task_registry.get(ticket["task_id"]).status is TaskStatus.COMPLETED
    )
    assert completed, "speaking task should have completed"

    listing = await client.get(f"/api/chatrooms/{room_id}/messages")
    assert listing.status_code == 200
    msgs = listing.json()["data"]["messages"]
    senders = [m["sender"] for m in msgs]
    assert "user" in senders
    assert "agent:planner" in senders
    planner_msg = next(m for m in msgs if m["sender"] == "agent:planner")
    assert planner_msg["status"] == "done"
    assert "got it" in planner_msg["content"]


@pytest.mark.asyncio
async def test_message_relays_to_second_agent_via_mention(client, deps):
    deps["cap_registry"].register_native(
        StreamingCap(
            "planner",
            [
                {
                    "type": "done",
                    "content": {"response": "好的，请 @reviewer 复核"},
                },
            ],
        )
    )
    deps["cap_registry"].register_native(
        StreamingCap(
            "reviewer",
            [
                {"type": "done", "content": {"response": "已审查通过"}},
            ],
        )
    )

    create = await client.post(
        "/api/chatrooms",
        json={"title": "review", "members": ["planner", "reviewer"]},
    )
    room_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/chatrooms/{room_id}/messages",
        json={"content": "@planner 准备方案"},
    )
    assert resp.status_code == 200

    task_registry: TaskRegistry = deps["task_registry"]
    finished = await _wait_for(
        lambda: len(task_registry.list()) >= 2
        and all(
            t.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED}
            for t in task_registry.list()
        ),
        timeout=3.0,
    )
    assert finished, "relay chain should have produced two completed tasks"

    listing = await client.get(f"/api/chatrooms/{room_id}/messages")
    msgs = listing.json()["data"]["messages"]
    senders = [m["sender"] for m in msgs]
    assert "agent:planner" in senders
    assert "agent:reviewer" in senders


@pytest.mark.asyncio
async def test_invoke_endpoint_returns_task_id_immediately(client, deps):
    deps["cap_registry"].register_native(
        StreamingCap(
            "planner",
            [
                {"type": "done", "content": {"response": "立即触发"}},
            ],
        )
    )

    create = await client.post(
        "/api/chatrooms",
        json={"title": "manual", "members": ["planner"]},
    )
    room_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/chatrooms/{room_id}/invoke",
        json={"agent_name": "planner", "prompt": "写一段话"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_id"]

    task_registry: TaskRegistry = deps["task_registry"]
    completed = await _wait_for(
        lambda: task_registry.get(data["task_id"]) is not None
        and task_registry.get(data["task_id"]).status is TaskStatus.COMPLETED,
        timeout=2.0,
    )
    assert completed


@pytest.mark.asyncio
async def test_cancel_endpoint_kills_in_flight_tasks(client, deps):
    class HangingCap(CapabilityBase):
        @property
        def name(self) -> str:  # type: ignore[override]
            return "planner"

        @property
        def description(self) -> str:  # type: ignore[override]
            return "hangs forever"

        def get_schema(self) -> CapabilitySchema:
            return CapabilitySchema(name="planner", description="hangs")

        async def execute(self, **kwargs):
            await asyncio.sleep(5.0)
            return {"response": "never"}

        async def execute_stream(self, **kwargs):
            yield {"type": "thinking", "content": "starting"}
            await asyncio.sleep(5.0)
            yield {"type": "done", "content": {"response": "never"}}

    deps["cap_registry"].register_native(HangingCap())

    create = await client.post(
        "/api/chatrooms",
        json={"title": "cancel", "members": ["planner"]},
    )
    room_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/chatrooms/{room_id}/invoke",
        json={"agent_name": "planner"},
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]

    task_registry: TaskRegistry = deps["task_registry"]
    streaming = await _wait_for(
        lambda: task_registry.get(task_id) is not None
        and task_registry.get(task_id).status is TaskStatus.RUNNING,
        timeout=2.0,
    )
    assert streaming

    cancel = await client.post(f"/api/chatrooms/{room_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["data"]["cancelled"] >= 1

    killed = await _wait_for(
        lambda: task_registry.get(task_id) is not None
        and task_registry.get(task_id).status is TaskStatus.KILLED,
        timeout=2.0,
    )
    assert killed


@pytest.mark.asyncio
async def test_unknown_member_invoke_returns_400(client, deps):
    create = await client.post(
        "/api/chatrooms",
        json={"title": "x", "members": ["planner"]},
    )
    room_id = create.json()["data"]["id"]
    resp = await client.post(
        f"/api/chatrooms/{room_id}/invoke",
        json={"agent_name": "ghost"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_message_without_mention_no_dispatch_unless_auto_host(client, deps):
    create = await client.post(
        "/api/chatrooms",
        json={"title": "silent", "members": ["planner"]},
    )
    room_id = create.json()["data"]["id"]
    resp = await client.post(
        f"/api/chatrooms/{room_id}/messages",
        json={"content": "纯发言不 @ 任何人"},
    )
    body = resp.json()["data"]
    assert body["mentions"] == []
    assert body["dispatched_tasks"] == []


@pytest.mark.asyncio
async def test_delete_room_kills_in_flight_tasks(client, deps):
    """删除房间应先级联 kill 所有 in-flight speaking task — Phase 4 review 修复。"""

    class HangingCap(CapabilityBase):
        @property
        def name(self) -> str:  # type: ignore[override]
            return "planner"

        @property
        def description(self) -> str:  # type: ignore[override]
            return "hangs"

        def get_schema(self) -> CapabilitySchema:
            return CapabilitySchema(name="planner", description="hangs")

        async def execute(self, **kwargs):
            await asyncio.sleep(5.0)
            return {"response": "never"}

        async def execute_stream(self, **kwargs):
            yield {"type": "thinking", "content": "starting"}
            await asyncio.sleep(5.0)
            yield {"type": "done", "content": {"response": "never"}}

    deps["cap_registry"].register_native(HangingCap())

    create = await client.post(
        "/api/chatrooms",
        json={"title": "del", "members": ["planner"]},
    )
    room_id = create.json()["data"]["id"]

    invoked = await client.post(
        f"/api/chatrooms/{room_id}/invoke",
        json={"agent_name": "planner"},
    )
    task_id = invoked.json()["data"]["task_id"]
    task_registry: TaskRegistry = deps["task_registry"]

    streaming = await _wait_for(
        lambda: task_registry.get(task_id) is not None
        and task_registry.get(task_id).status is TaskStatus.RUNNING,
        timeout=2.0,
    )
    assert streaming

    delete = await client.delete(f"/api/chatrooms/{room_id}")
    assert delete.status_code == 200
    # delete 返回里告知本次取消了多少 task
    assert delete.json()["data"]["cancelled"] >= 1

    killed = await _wait_for(
        lambda: task_registry.get(task_id) is not None
        and task_registry.get(task_id).status is TaskStatus.KILLED,
        timeout=2.0,
    )
    assert killed


@pytest.mark.asyncio
async def test_auto_host_emits_system_notice_when_host_not_in_room(client, deps):
    """auto_host 开了但 host_agent 不在 members 里时，不能静默忽略 — 应写一条 system 消息。"""

    create = await client.post(
        "/api/chatrooms",
        json={
            "title": "lonely",
            "members": ["coder"],
            "settings": {"auto_host": True, "host_agent": "planner"},
        },
    )
    room_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/chatrooms/{room_id}/messages",
        json={"content": "没有 @ 任何人"},
    )
    body = resp.json()["data"]
    assert body["mentions"] == []
    assert body["dispatched_tasks"] == []

    room = (await client.get(f"/api/chatrooms/{room_id}")).json()["data"]
    notices = [m for m in room["messages"] if m["sender"] == "system"]
    assert any("auto_host" in m["content"] for m in notices), (
        f"没找到 auto_host 兜底 system 消息：{[m['content'] for m in notices]}"
    )
