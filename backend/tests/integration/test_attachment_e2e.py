"""B1 attachment e2e — upload → reference → Agent sees → delete (Plan 3 P3 Task 28).

Stitches the four pieces of the attachment lifecycle together using the real
FastAPI route handlers (no LLM, no real Agent) so we catch contract drift
between the upload endpoint, the message-attachments wiring, the
``invoke_agent`` payload assembly path and the delete endpoint.

The test exercises BOTH attachment shapes covered by Tasks 25/26:

* a non-image (``text/plain``) — checked under the system-reminder route
  (``<attached_files>`` block + workspace-local materialization);
* an image (``image/png``) — checked under the vision route
  (``payload["attachment_images"]`` carrying inlined base64 + correct mime).

The Agent capability is replaced by a tiny stub that captures whatever
arguments ``execute`` receives, so we can assert on the payload that would
hit the LLM.
"""

from __future__ import annotations

import base64
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.attachment import AttachmentStore  # noqa: E402


# ─── App / fixtures ─────────────────────────────────────────────────────


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
def attachment_store(tmp_path):
    from api.routes import attachments as attachments_route

    store = AttachmentStore(root=tmp_path / "store")
    attachments_route.set_attachment_store(store)
    yield store
    attachments_route.set_attachment_store(None)


@pytest.fixture
async def upload_client(attachment_store):  # noqa: ARG001
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ─── Helpers ────────────────────────────────────────────────────────────


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-payload"


async def _async_zero_memory(_query):
    return "", 0


async def _invoke_agent_capture(captured: dict, attachment_ids, *, monkeypatch, tmp_path):
    """Drive ``invoke_agent`` and capture the kwargs sent to the capability."""

    from api.routes import agents as agents_route_module
    from api.schemas import AgentInvokeRequest

    class _FakeRegistry:
        def __contains__(self, name):
            return name == "demo"

        async def execute(self, name, **kwargs):
            captured.update(kwargs)
            return {"output": "ok"}

    monkeypatch.setattr(
        agents_route_module, "get_capability_registry", lambda: _FakeRegistry()
    )

    workspace_root = tmp_path / "ws"
    workspace_root.mkdir(exist_ok=True)

    def _fake_attach(payload, agent_name):
        payload["_trusted_workspace_root"] = str(workspace_root)
        return None

    monkeypatch.setattr(
        agents_route_module, "_attach_trusted_workspace_context", _fake_attach
    )
    monkeypatch.setattr(agents_route_module, "build_memory_context", _async_zero_memory)
    monkeypatch.setattr(
        agents_route_module, "schedule_memory_reflection", lambda **kw: None
    )

    req = AgentInvokeRequest(
        data={
            "message": "看附件",
            "input": "看附件",
            "attachments": list(attachment_ids),
            "session_id": "s-e2e",
        }
    )
    response = await agents_route_module.invoke_agent("demo", req)
    assert response.status == "ok"
    return workspace_root


# ─── Test ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attachment_e2e_upload_reference_agent_consume_delete(
    upload_client, attachment_store, monkeypatch, tmp_path
):
    """End-to-end happy path covering both vision + system-reminder routes."""

    # ─── 1. Upload — text + png via REST ───────────────────────────
    text_res = await upload_client.post(
        "/api/attachments?scope=chat_session:s-e2e",
        files={"file": ("notes.txt", b"hello agent", "text/plain")},
    )
    assert text_res.status_code == 200, text_res.text
    text_id = text_res.json()["data"]["id"]

    img_res = await upload_client.post(
        "/api/attachments?scope=chat_session:s-e2e",
        files={"file": ("pic.png", PNG_BYTES, "image/png")},
    )
    assert img_res.status_code == 200, img_res.text
    img_id = img_res.json()["data"]["id"]

    # Listing surfaces both ids — ensures the index round-tripped to disk.
    listing = await upload_client.get(
        "/api/attachments?scope=chat_session:s-e2e"
    )
    listing_ids = {row["id"] for row in listing.json()["data"]}
    assert text_id in listing_ids
    assert img_id in listing_ids

    # ─── 2. Message reference — invoke_agent with attachments=[text, img]
    captured: dict = {}
    workspace_root = await _invoke_agent_capture(
        captured,
        [text_id, img_id],
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    # ─── 3. Agent sees both — non-image via system reminder, image via
    # vision payload. Failure here means the wiring regressed.
    serialized = repr(captured)
    assert "<attached_files>" in serialized, serialized
    assert "notes.txt" in serialized
    assert text_id in serialized

    # Materialized file should now exist under workspace .attachments/
    materialized_text = workspace_root / ".attachments" / text_id / "notes.txt"
    assert materialized_text.exists()
    assert materialized_text.read_bytes() == b"hello agent"

    images = captured.get("attachment_images")
    assert isinstance(images, list) and len(images) == 1
    img_block = images[0]
    assert img_block["mime_type"] == "image/png"
    assert base64.b64decode(img_block["data"]) == PNG_BYTES
    assert img_block.get("name") == "pic.png"

    # Image must NOT have ended up in the system reminder / read_file path.
    assert "pic.png" not in captured.get("attachment_context", "")

    # ─── 4. Delete — DELETE returns 200/204, file gone from store ───
    del_text = await upload_client.delete(f"/api/attachments/{text_id}")
    assert del_text.status_code in (200, 204), del_text.text
    del_img = await upload_client.delete(f"/api/attachments/{img_id}")
    assert del_img.status_code in (200, 204), del_img.text
    assert attachment_store.get(text_id) is None
    assert attachment_store.get(img_id) is None

    # Subsequent invoke with the deleted ids should be a no-op (no
    # attachment_context / attachment_images leak).
    captured2: dict = {}
    await _invoke_agent_capture(
        captured2,
        [text_id, img_id],
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert "attachment_images" not in captured2 or not captured2["attachment_images"]
    serialized2 = captured2.get("attachment_context", "")
    assert text_id not in serialized2
    assert img_id not in serialized2
