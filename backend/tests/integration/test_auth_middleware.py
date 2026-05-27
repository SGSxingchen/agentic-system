"""A11 — HTTP 鉴权中间件集成测试 (Task 15)。

覆盖：
- /api/health 永远豁免鉴权
- 未配置密码时所有 /api/* 都直通
- 配置密码后未带 token → 401 auth_required
- 错误 token → 401 auth_invalid
- 正确 token → 通过
- 同一 IP 在窗口内 ≥ failed_login_max_attempts 失败 → 后续请求即使带正确 token 也被锁定 429
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

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


def _build_app_with_auth() -> "object":
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from api.routes import agents_router, config_router

    @asynccontextmanager
    async def _noop_lifespan(app):  # noqa: ARG001
        yield

    app = FastAPI(lifespan=_noop_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware)
    app.include_router(agents_router)
    app.include_router(config_router)
    return app


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

    yield None

    await bus.stop()
    set_bus(None)
    set_agent_registry(None)
    set_capability_registry(None)
    set_reload_agent_fn(None)


def _patch_system_config(monkeypatch, *, password: str, max_attempts: int = 5, lockout: int = 60) -> None:
    """让 middleware 看到指定的 ServerConfig。"""

    fake = SystemConfig(
        server=ServerConfig(
            access_password=password,
            failed_login_max_attempts=max_attempts,
            failed_login_lockout_seconds=lockout,
        )
    )
    monkeypatch.setattr("api.middleware.auth.get_system_config", lambda: fake)


@pytest.fixture
async def client(deps):
    app = _build_app_with_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testclient") as c:
        yield c


# ─── 健康检查永远豁免 ───────────────────────────────


async def test_health_never_requires_auth(client, monkeypatch):
    """A11: /api/health 即便配置了密码也不要求 token。"""

    _patch_system_config(monkeypatch, password="s3cret")
    res = await client.get("/api/health")
    assert res.status_code == 200


# ─── 没配置密码时直通 ───────────────────────────────


async def test_no_password_passes_through(client, monkeypatch):
    """A11: access_password 为空时所有 API 不需要 token。"""

    _patch_system_config(monkeypatch, password="")
    res = await client.get("/api/agents")
    assert res.status_code == 200


# ─── 401 / 锁定核心场景 ────────────────────────────


async def test_other_api_requires_token_when_password_set(client, monkeypatch):
    """A11: 配置密码后，没带 Authorization 必须 401 auth_required。"""

    _patch_system_config(monkeypatch, password="s3cret")
    res = await client.get("/api/agents")
    assert res.status_code == 401
    body = res.json()
    assert body.get("error") == "auth_required"


async def test_correct_token_passes(client, monkeypatch):
    """A11: 正确 Bearer token 应该被放行。"""

    _patch_system_config(monkeypatch, password="s3cret")
    res = await client.get("/api/agents", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200


async def test_wrong_token_returns_401_auth_invalid(client, monkeypatch):
    """A11: 错误 Bearer token 必须 401 auth_invalid。"""

    _patch_system_config(monkeypatch, password="s3cret")
    res = await client.get(
        "/api/agents",
        headers={"Authorization": "Bearer wrong"},
    )
    assert res.status_code == 401
    assert res.json().get("error") == "auth_invalid"


async def test_lockout_after_max_failures(client, monkeypatch):
    """A11: 同一 IP 累计 ≥ failed_login_max_attempts 错误 token 后，后续请求即使带正确 token 也被锁定 429。"""

    _patch_system_config(monkeypatch, password="s3cret", max_attempts=5, lockout=60)
    for _ in range(5):
        await client.get(
            "/api/agents",
            headers={"Authorization": "Bearer wrong"},
        )

    res = await client.get(
        "/api/agents",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert res.status_code == 429
    assert res.json().get("error") == "rate_limited"


async def test_non_api_paths_passthrough(client, monkeypatch):
    """A11: 非 /api/* 路径不被中间件拦（让静态资源、/docs 之类正常走）。"""

    _patch_system_config(monkeypatch, password="s3cret")
    res = await client.get("/openapi.json")
    # FastAPI 默认开 /openapi.json，应可访问
    assert res.status_code in {200, 404}  # 测试 app 没启 docs 也行


async def test_bearer_prefix_required(client, monkeypatch):
    """A11: 没有 Bearer 前缀的 Authorization header 视为 auth_required。"""

    _patch_system_config(monkeypatch, password="s3cret")
    res = await client.get(
        "/api/agents",
        headers={"Authorization": "Token s3cret"},
    )
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"
