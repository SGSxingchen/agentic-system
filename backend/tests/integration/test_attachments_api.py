"""Integration tests for attachments REST API (B1 — Plan 3 P3 Task 21).

Covers POST/GET/DELETE/LIST under /api/attachments with size + MIME guards.

The route module exposes ``set_attachment_store`` and reads its size/MIME limits
through ``get_attachment_settings`` so tests can swap in a tmp store and tweak
limits without touching ``config/system.yaml``.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.attachment import AttachmentStore  # noqa: E402


def _build_app():
    from fastapi import FastAPI

    from api.routes.attachments import router as attachments_router

    @asynccontextmanager
    async def _noop_lifespan(app):  # noqa: ARG001
        yield

    app = FastAPI(lifespan=_noop_lifespan)
    app.include_router(attachments_router)
    return app


@pytest.fixture
def store_root(tmp_path):
    return tmp_path / "attachments"


@pytest.fixture
def attachment_store(store_root):
    from api.routes import attachments as attachments_route

    store = AttachmentStore(root=store_root)
    attachments_route.set_attachment_store(store)
    yield store
    attachments_route.set_attachment_store(None)


@pytest.fixture
def settings_override():
    """Reset settings after each test to avoid bleed-over."""

    from api.routes import attachments as attachments_route

    original = attachments_route._settings_override.copy()
    yield attachments_route
    attachments_route._settings_override.clear()
    attachments_route._settings_override.update(original)


@pytest.fixture
async def client(attachment_store, settings_override):  # noqa: ARG001
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_upload_attachment_returns_id(client):
    files = {"file": ("hello.txt", b"hello world", "text/plain")}
    res = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["id"]
    assert data["filename"] == "hello.txt"
    assert data["mime_type"] == "text/plain"
    assert data["size_bytes"] == len(b"hello world")
    assert data["scope"] == "chatroom:r1"


@pytest.mark.asyncio
async def test_upload_too_large_rejected(client, settings_override):
    settings_override._settings_override["max_size_bytes"] = 16
    files = {"file": ("big.bin", b"x" * 32, "application/octet-stream")}
    # Even though octet-stream may not be in allowed list, size guard runs first.
    settings_override._settings_override["allowed_mime_prefixes"] = ["application/"]
    res = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    assert res.status_code == 413
    body = res.json()
    assert "too large" in (body.get("detail") or "").lower()


@pytest.mark.asyncio
async def test_upload_blocked_mime_rejected(client, settings_override):
    settings_override._settings_override["allowed_mime_prefixes"] = ["image/", "text/"]
    files = {"file": ("evil.exe", b"...", "application/x-executable")}
    res = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    assert res.status_code == 415
    body = res.json()
    assert "mime" in (body.get("detail") or "").lower() or "type" in (body.get("detail") or "").lower()


@pytest.mark.asyncio
async def test_upload_requires_scope(client):
    files = {"file": ("hello.txt", b"hello", "text/plain")}
    res = await client.post("/api/attachments", files=files)
    # FastAPI returns 422 when query param missing.
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_download_attachment_returns_bytes(client):
    files = {"file": ("dl.txt", b"download me", "text/plain")}
    create = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    att_id = create.json()["data"]["id"]

    download = await client.get(f"/api/attachments/{att_id}/content")
    assert download.status_code == 200
    assert download.content == b"download me"
    assert download.headers.get("content-type", "").startswith("text/plain")


@pytest.mark.asyncio
async def test_download_unknown_returns_404(client):
    res = await client.get("/api/attachments/nope/content")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_metadata(client):
    files = {"file": ("m.txt", b"meta", "text/plain")}
    create = await client.post("/api/attachments?scope=chatroom:rM", files=files)
    att_id = create.json()["data"]["id"]

    res = await client.get(f"/api/attachments/{att_id}")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["id"] == att_id
    assert data["filename"] == "m.txt"
    # storage_path should not leak in metadata
    assert "storage_path" not in data


@pytest.mark.asyncio
async def test_list_by_scope(client):
    await client.post(
        "/api/attachments?scope=chatroom:rL",
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    await client.post(
        "/api/attachments?scope=chatroom:rL",
        files={"file": ("b.txt", b"b", "text/plain")},
    )
    await client.post(
        "/api/attachments?scope=chat_session:other",
        files={"file": ("c.txt", b"c", "text/plain")},
    )

    res = await client.get("/api/attachments?scope=chatroom:rL")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 2
    assert {row["filename"] for row in data} == {"a.txt", "b.txt"}

    # List without scope returns everything currently in store.
    all_res = await client.get("/api/attachments")
    assert len(all_res.json()["data"]) == 3


@pytest.mark.asyncio
async def test_delete_attachment(client):
    create = await client.post(
        "/api/attachments?scope=chatroom:rD",
        files={"file": ("d.txt", b"del", "text/plain")},
    )
    att_id = create.json()["data"]["id"]

    res = await client.delete(f"/api/attachments/{att_id}")
    assert res.status_code == 200

    follow = await client.get(f"/api/attachments/{att_id}")
    assert follow.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_returns_404(client):
    res = await client.delete("/api/attachments/missing")
    assert res.status_code == 404
