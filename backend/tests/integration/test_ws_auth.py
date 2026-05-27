"""A11 — WebSocket 鉴权集成测试 (Task 16)。

WS 协议无 ``Authorization`` header，因此走 ``?token=<password>`` query 参数。
- token 缺失 / 错误 → 服务端 close code 4401（4000-4999 自定义区，约定为 auth_invalid）
- 空 ``access_password`` 时不强制 token，保留对开发者无门禁的体验
- 正确 token → 正常 accept，能 ping/pong
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import ServerConfig, SystemConfig

from api.websocket.handlers import websocket_endpoint, manager as global_manager


def _build_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_: FastAPI):  # noqa: ARG001
        yield

    app = FastAPI(lifespan=_lifespan)
    app.add_websocket_route("/ws", websocket_endpoint)
    return app


def _patch_password(monkeypatch, password: str) -> None:
    fake = SystemConfig(server=ServerConfig(access_password=password))
    monkeypatch.setattr("api.websocket.handlers.get_system_config", lambda: fake)


def test_ws_no_token_closes_4401(monkeypatch):
    """A11: 未带 token 应被 close(code=4401, reason=auth_invalid)。"""

    _patch_password(monkeypatch, "s3cret")
    global_manager._channels.clear()
    app = _build_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # 读取应触发 close 异常
    assert exc.value.code == 4401


def test_ws_wrong_token_closes_4401(monkeypatch):
    """A11: 错误 token 也走 4401。"""

    _patch_password(monkeypatch, "s3cret")
    global_manager._channels.clear()
    app = _build_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_correct_token_connects(monkeypatch):
    """A11: 正确 token 应能正常 accept，ping/pong 通畅。"""

    _patch_password(monkeypatch, "s3cret")
    global_manager._channels.clear()
    app = _build_app()
    client = TestClient(app)

    with client.websocket_connect("/ws?token=s3cret") as ws:
        ws.send_json({"event_type": "ping"})
        msg = ws.receive_json()
        assert msg.get("event_type") == "pong"


def test_ws_no_password_configured_allows_anonymous(monkeypatch):
    """A11: ``access_password`` 为空时不强制 token，保留无门禁开发体验。"""

    _patch_password(monkeypatch, "")
    global_manager._channels.clear()
    app = _build_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"event_type": "ping"})
        msg = ws.receive_json()
        assert msg.get("event_type") == "pong"
