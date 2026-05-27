"""Integration test for B1 Agent attachment consume — non-image path (Task 25).

Two layers:

1. Unit-level: ``build_attachment_reminder`` in ``core.attachment_message_context``
   must materialize attachments into the workspace and return an ``<attached_files>``
   system reminder string referencing each attachment's *workspace* path
   (so ``read_file`` is allowed to read them under the sandbox).
2. Integration-level: the helper must be wired into ``invoke_agent`` so that
   when a request carries ``attachments=[...]`` the system prompt seen by the
   capability includes the ``<attached_files>`` block. We assert this via a
   fake CapabilityRegistry that records ``execute`` arguments.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.attachment import AttachmentStore  # noqa: E402
from core.attachment_message_context import build_attachment_reminder  # noqa: E402


# ============================== unit ==============================


def test_build_attachment_reminder_materializes_and_returns_block(tmp_path):
    store = AttachmentStore(root=tmp_path / "store")
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()

    txt = store.create(
        filename="hello.txt",
        mime_type="text/plain",
        content=b"hi there",
        scope="chat_session:s1",
        uploaded_by="user",
    )
    pdf = store.create(
        filename="paper.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4 fake",
        scope="chat_session:s1",
        uploaded_by="user",
    )
    block = build_attachment_reminder(
        attachment_ids=[txt.id, pdf.id],
        workspace_root=workspace_root,
        store=store,
    )

    # Block contains XML-ish tag and one <file/> per attachment.
    assert "<attached_files>" in block
    assert "</attached_files>" in block
    assert block.count("<file ") == 2
    # Each file references its workspace-local path under .attachments/.
    materialized_txt = workspace_root / ".attachments" / txt.id / "hello.txt"
    materialized_pdf = workspace_root / ".attachments" / pdf.id / "paper.pdf"
    assert materialized_txt.read_bytes() == b"hi there"
    assert materialized_pdf.read_bytes() == b"%PDF-1.4 fake"
    # Path appears in the reminder so the Agent knows what to feed read_file.
    assert "hello.txt" in block
    assert "paper.pdf" in block
    assert "text/plain" in block
    assert "application/pdf" in block


def test_build_attachment_reminder_skips_image_types(tmp_path):
    """Images go through vision payload (Task 26), not the read_file path."""

    store = AttachmentStore(root=tmp_path / "store")
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    img = store.create(
        filename="pic.png",
        mime_type="image/png",
        content=b"\x89PNG\r\n",
        scope="chat_session:s1",
        uploaded_by="user",
    )
    txt = store.create(
        filename="notes.md",
        mime_type="text/markdown",
        content=b"# notes",
        scope="chat_session:s1",
        uploaded_by="user",
    )
    block = build_attachment_reminder(
        attachment_ids=[img.id, txt.id],
        workspace_root=workspace_root,
        store=store,
    )
    # Only the markdown file should be in the reminder.
    assert block.count("<file ") == 1
    assert "notes.md" in block
    assert "pic.png" not in block


def test_build_attachment_reminder_returns_empty_when_no_ids(tmp_path):
    store = AttachmentStore(root=tmp_path / "store")
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    block = build_attachment_reminder(
        attachment_ids=[],
        workspace_root=workspace_root,
        store=store,
    )
    assert block == ""


def test_build_attachment_reminder_skips_unknown_ids(tmp_path):
    store = AttachmentStore(root=tmp_path / "store")
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    block = build_attachment_reminder(
        attachment_ids=["nope-1", "nope-2"],
        workspace_root=workspace_root,
        store=store,
    )
    assert block == ""


# ============================== integration ==============================


@pytest.mark.asyncio
async def test_invoke_agent_passes_attachment_reminder_into_payload(tmp_path, monkeypatch):
    """``POST /api/agents/{name}/invoke`` with attachments → reminder appears in capability call."""

    # Wire a real attachment store at a temp root.
    from core.attachment import AttachmentStore as _Store
    import api.routes.attachments as attachments_routes
    test_store = _Store(root=tmp_path / "store")
    attachments_routes.set_attachment_store(test_store)
    att = test_store.create(
        filename="readme.txt",
        mime_type="text/plain",
        content=b"hello agent",
        scope="chat_session:s1",
        uploaded_by="user",
    )

    # Capture what the registry receives.
    captured: dict = {}

    class _FakeCap:
        async def execute(self, **kwargs):
            captured.update(kwargs)
            return {"output": "ok"}

    class _FakeRegistry:
        def __contains__(self, name):
            return name == "demo"

        async def execute(self, name, **kwargs):
            captured.update(kwargs)
            return {"output": "ok"}

    from api.routes import agents as agents_route_module
    monkeypatch.setattr(
        agents_route_module, "get_capability_registry", lambda: _FakeRegistry()
    )

    # Stub workspace context attach so the workspace_root override is accepted.
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()

    def _fake_attach(payload, agent_name):
        payload["_trusted_workspace_root"] = str(workspace_root)
        return None

    monkeypatch.setattr(
        agents_route_module, "_attach_trusted_workspace_context", _fake_attach
    )
    monkeypatch.setattr(
        agents_route_module, "build_memory_context", _async_zero_memory
    )
    monkeypatch.setattr(
        agents_route_module, "schedule_memory_reflection", lambda **kw: None
    )

    from api.schemas import AgentInvokeRequest

    req = AgentInvokeRequest(
        data={
            "message": "看看附件",
            "input": "看看附件",
            "attachments": [att.id],
            "session_id": "s1",
        }
    )
    response = await agents_route_module.invoke_agent("demo", req)
    assert response.status == "ok"

    # The capability must have been called with a system_reminder/messages slot
    # that contains the <attached_files> block.
    serialized = repr(captured)
    assert "<attached_files>" in serialized
    assert "readme.txt" in serialized
    assert att.id in serialized


async def _async_zero_memory(_query):
    return "", 0
