"""A11 — 全局密码门禁 e2e 集成测试 (Task 19)。

把 HTTP 中间件、WS 鉴权、IP 锁定三套场景串到同一个 FastAPI app 里跑，
保证它们组合起来不会互相打架（比如锁定计数泄漏到 WS、CORS 在 401 时丢 header）。

覆盖矩阵：
- HTTP 401: 缺 token / 错误 token
- HTTP 200: 正确 token
- HTTP 200: /api/health 永远豁免
- HTTP 429: 单 IP 累计 max_attempts 错误后锁定
- HTTP 锁定不影响 /api/health 豁免
- WS 4401: 缺 token / 错误 token
- WS accept: 正确 token
- 没配密码时 HTTP + WS 都直通
- HTTP 锁定不影响 WS 鉴权独立计数（WS close 4401 不走 HTTP middleware）
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.agent import AgentRegistry
from core.bus import SimpleBus
from core.capability import CapabilityRegistry
from core.config import ServerConfig, SystemConfig

from api.dependencies import (
    set_agent_registry,
    set_bus,
    set_capability_registry,
    set_reload_agent_fn,
)
from api.middleware.auth import AuthMiddleware
from api.routes import agents_router, config_router
from api.websocket.handlers import (
    manager as global_ws_manager,
    websocket_endpoint,
)


def _build_full_app() -> FastAPI:
    """A11 e2e 用的最小 app：路由 + Auth + CORS + WS endpoint。

    顺序与 main.py 一致：先注册 Auth，再注册 CORS（CORS 是外层）。
    """

    @asynccontextmanager
    async def _lifespan(_: FastAPI):  # noqa: ARG001
        yield

    app = FastAPI(lifespan=_lifespan)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(agents_router)
    app.include_router(config_router)
    app.add_websocket_route("/ws", websocket_endpoint)
    return app


def _patch_password(monkeypatch, *, password: str, max_attempts: int = 5, lockout: int = 60) -> None:
    fake = SystemConfig(
        server=ServerConfig(
            access_password=password,
            failed_login_max_attempts=max_attempts,
            failed_login_lockout_seconds=lockout,
        )
    )
    # HTTP middleware 与 WS handler 各自从 core.config.get_system_config 取，
    # patch 两个引用都覆盖（middleware 用 from-import，handler 也是 from-import）
    monkeypatch.setattr("api.middleware.auth.get_system_config", lambda: fake)
    monkeypatch.setattr("api.websocket.handlers.get_system_config", lambda: fake)


@pytest.fixture
async def deps():
    bus = SimpleBus()
    await bus.start()
    registry = AgentRegistry()
    cap_registry = CapabilityRegistry()

    set_bus(bus)
    set_agent_registry(registry)
    set_capability_registry(cap_registry)
    set_reload_agent_fn(AsyncMock())

    # 重置全局 WS manager 频道表，防止上一个测试残留
    global_ws_manager._channels.clear()

    yield None

    await bus.stop()
    set_bus(None)
    set_agent_registry(None)
    set_capability_registry(None)
    set_reload_agent_fn(None)


@pytest.fixture
async def http_client(deps):
    app = _build_full_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://e2e-test") as c:
        yield c


# ========================
# Group 1：HTTP 鉴权场景
# ========================


async def test_e2e_http_health_never_requires_auth(http_client, monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    res = await http_client.get("/api/health")
    assert res.status_code == 200


async def test_e2e_http_no_token_returns_auth_required(http_client, monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    res = await http_client.get("/api/agents")
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


async def test_e2e_http_correct_token_passes(http_client, monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    res = await http_client.get(
        "/api/agents",
        headers={"Authorization": "Bearer topsecret"},
    )
    assert res.status_code == 200


async def test_e2e_http_wrong_token_returns_auth_invalid(http_client, monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    res = await http_client.get(
        "/api/agents",
        headers={"Authorization": "Bearer wrong"},
    )
    assert res.status_code == 401
    assert res.json().get("error") == "auth_invalid"


async def test_e2e_http_no_password_passthrough(http_client, monkeypatch):
    _patch_password(monkeypatch, password="")
    res = await http_client.get("/api/agents")
    assert res.status_code == 200


# ========================
# Group 2：IP 锁定场景
# ========================


async def test_e2e_http_lockout_after_max_attempts(http_client, monkeypatch):
    """连续 5 次错误 token → 第 6 次即使带正确 token 也 429。"""

    _patch_password(monkeypatch, password="topsecret", max_attempts=5)
    for _ in range(5):
        await http_client.get(
            "/api/agents",
            headers={"Authorization": "Bearer wrong"},
        )

    res = await http_client.get(
        "/api/agents",
        headers={"Authorization": "Bearer topsecret"},
    )
    assert res.status_code == 429
    assert res.json().get("error") == "rate_limited"


async def test_e2e_http_lockout_does_not_block_health(http_client, monkeypatch):
    """锁定状态下 /api/health 仍然可访问（健康探针不能被门挡住）。"""

    _patch_password(monkeypatch, password="topsecret", max_attempts=2)
    for _ in range(2):
        await http_client.get(
            "/api/agents",
            headers={"Authorization": "Bearer wrong"},
        )

    # 锁定中
    locked = await http_client.get(
        "/api/agents",
        headers={"Authorization": "Bearer topsecret"},
    )
    assert locked.status_code == 429

    # 但 health 不受影响
    health = await http_client.get("/api/health")
    assert health.status_code == 200


# ========================
# Group 3：WebSocket 鉴权场景
# ========================


def test_e2e_ws_no_token_closes_4401(monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    global_ws_manager._channels.clear()
    app = _build_full_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_e2e_ws_wrong_token_closes_4401(monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    global_ws_manager._channels.clear()
    app = _build_full_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=guess") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_e2e_ws_correct_token_connects(monkeypatch):
    _patch_password(monkeypatch, password="topsecret")
    global_ws_manager._channels.clear()
    app = _build_full_app()
    client = TestClient(app)

    with client.websocket_connect("/ws?token=topsecret") as ws:
        ws.send_json({"event_type": "ping"})
        msg = ws.receive_json()
        assert msg.get("event_type") == "pong"


def test_e2e_ws_no_password_allows_anonymous(monkeypatch):
    _patch_password(monkeypatch, password="")
    global_ws_manager._channels.clear()
    app = _build_full_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"event_type": "ping"})
        msg = ws.receive_json()
        assert msg.get("event_type") == "pong"


# ========================
# Group 4：HTTP 锁定与 WS 通道独立
# ========================


def test_e2e_ws_independent_from_http_lockout(monkeypatch):
    """WS 鉴权独立于 HTTP 失败计数：HTTP 锁定不会拒绝带正确 token 的 WS。"""

    # 先开短窗口让 HTTP 锁定快速触发
    _patch_password(monkeypatch, password="topsecret", max_attempts=1)
    global_ws_manager._channels.clear()
    app = _build_full_app()
    client = TestClient(app)

    # HTTP 错一次直接锁
    bad = client.get("/api/agents", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401
    locked = client.get("/api/agents", headers={"Authorization": "Bearer topsecret"})
    assert locked.status_code == 429

    # 但 WS 仍能用正确 token 连进来（WS 不走 HTTP middleware 的失败计数）
    with client.websocket_connect("/ws?token=topsecret") as ws:
        ws.send_json({"event_type": "ping"})
        msg = ws.receive_json()
        assert msg.get("event_type") == "pong"
