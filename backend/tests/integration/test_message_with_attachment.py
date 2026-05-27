"""Schema-level acceptance tests for messages with ``attachments`` (B1 Task 22).

Per Phase P3 contract, the request schema accepts an optional list of
attachment IDs alongside the message content. Wiring the field into the
storage layer (chat_history / chatroom message normalisation) is intentionally
deferred to a later task — these tests therefore only assert that the
Pydantic schema parses ``attachments`` cleanly and that the REST endpoints
return 200 when the field is included.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.chat_history import ChatHistoryStore  # noqa: E402
from core.chatroom import ChatroomStore  # noqa: E402


# ============================== schema unit ===============================


def test_chat_message_request_accepts_attachments():
    """``ChatMessageCreateRequest`` must declare ``attachments`` as optional list."""

    from api.schemas import ChatMessageCreateRequest

    req = ChatMessageCreateRequest(
        type="user",
        content="hello",
        attachments=["a", "b"],
    )
    assert req.attachments == ["a", "b"]
    payload = req.model_dump(exclude_none=True)
    assert payload["attachments"] == ["a", "b"]


def test_chat_message_request_attachments_default_none():
    from api.schemas import ChatMessageCreateRequest

    req = ChatMessageCreateRequest(type="user", content="hello")
    # Optional → default None; with exclude_none, the key is dropped.
    assert req.attachments is None
    assert "attachments" not in req.model_dump(exclude_none=True)


def test_chatroom_message_request_accepts_attachments():
    from api.schemas import ChatroomMessageCreateRequest

    req = ChatroomMessageCreateRequest(content="hi", attachments=["x"])
    assert req.attachments == ["x"]


def test_chatroom_message_request_attachments_default_none():
    from api.schemas import ChatroomMessageCreateRequest

    req = ChatroomMessageCreateRequest(content="hi")
    assert req.attachments is None


# ============================== chat session ==============================


def _build_chat_app(monkeypatch, store_path: Path):
    from fastapi import FastAPI

    from api.routes import chat_sessions as chat_route

    monkeypatch.setattr(
        chat_route,
        "_store",
        lambda: ChatHistoryStore(path=store_path),
    )

    @asynccontextmanager
    async def _noop_lifespan(app):  # noqa: ARG001
        yield

    app = FastAPI(lifespan=_noop_lifespan)
    app.include_router(chat_route.router)
    return app


@pytest.mark.asyncio
async def test_chat_session_accepts_attachments_field(monkeypatch, tmp_path):
    """POST /api/chat-sessions/{id}/messages must accept attachments without 422."""

    app = _build_chat_app(monkeypatch, tmp_path / "sessions.json")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/api/chat-sessions", json={"title": "T"})
        assert create.status_code == 200, create.text
        sid = create.json()["data"]["id"]

        body = {
            "type": "user",
            "content": "see attachment please",
            "attachments": ["att-1", "att-2"],
        }
        res = await client.post(f"/api/chat-sessions/{sid}/messages", json=body)
        assert res.status_code == 200, res.text


# ============================== chatroom ==================================


def _build_chatroom_app(monkeypatch, room_root: Path):
    from fastapi import FastAPI

    from api.routes import chatrooms as chatroom_route

    store = ChatroomStore(root=room_root)
    monkeypatch.setattr(chatroom_route, "_store", lambda: store)

    @asynccontextmanager
    async def _noop_lifespan(app):  # noqa: ARG001
        yield

    app = FastAPI(lifespan=_noop_lifespan)
    app.include_router(chatroom_route.router)
    return app, store


@pytest.mark.asyncio
async def test_chatroom_accepts_attachments_field(monkeypatch, tmp_path):
    """POST /api/chatrooms/{id}/messages must accept attachments without 422."""

    app, store = _build_chatroom_app(monkeypatch, tmp_path)
    room = store.create_room(title="R", topic="t", goal="g", members=[])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = {
            "content": "look at this",  # no @mention so dispatch is a no-op
            "attachments": ["att-x"],
        }
        res = await client.post(f"/api/chatrooms/{room['id']}/messages", json=body)
        assert res.status_code == 200, res.text
