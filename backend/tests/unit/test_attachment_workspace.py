"""Unit tests for ``core.attachment_workspace`` (B1 — Plan 3 Phase P3 Task 24).

Covers the symlink (Linux) / ``shutil.copy2`` (Windows) fallback path that lets
Agent ``read_file`` see attachments inside a sandboxed workspace root.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Same convention as the other unit tests.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.attachment import AttachmentStore  # noqa: E402
from core.attachment_workspace import link_attachment_to_workspace  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return AttachmentStore(root=tmp_path / "att-store")


@pytest.fixture
def workspace_root(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return root


def test_link_creates_target_under_dot_attachments(store, workspace_root):
    att = store.create(
        filename="hello.txt",
        mime_type="text/plain",
        content=b"hi",
        scope="chatroom:r1",
        uploaded_by="user",
    )
    target = link_attachment_to_workspace(att, workspace_root)
    assert target.parent == workspace_root / ".attachments" / att.id
    assert target.name == "hello.txt"
    # Whatever the linking strategy, the file content should be readable.
    assert target.read_bytes() == b"hi"


def test_link_is_idempotent(store, workspace_root):
    att = store.create(
        filename="hello.txt",
        mime_type="text/plain",
        content=b"hi",
        scope="chatroom:r1",
        uploaded_by="user",
    )
    a = link_attachment_to_workspace(att, workspace_root)
    b = link_attachment_to_workspace(att, workspace_root)
    assert a == b
    assert a.read_bytes() == b"hi"


def test_link_falls_back_to_copy_when_symlink_unsupported(
    store, workspace_root, monkeypatch
):
    """When ``Path.symlink_to`` raises (R6 Windows fallback), copy the file."""

    att = store.create(
        filename="winfile.txt",
        mime_type="text/plain",
        content=b"hello windows",
        scope="chatroom:r1",
        uploaded_by="user",
    )

    original_symlink_to = Path.symlink_to

    def _raise(self, *args, **kwargs):  # type: ignore[no-redef]
        raise OSError(1314, "symlink privilege not held")

    monkeypatch.setattr(Path, "symlink_to", _raise)

    target = link_attachment_to_workspace(att, workspace_root)
    # Even with no symlink support, we got the file with full content.
    assert target.exists()
    assert target.read_bytes() == b"hello windows"
    # And it must be a real file (a *copy*), not a dangling symlink.
    assert target.is_file()
    assert not target.is_symlink()

    # Restore (just in case the monkeypatch leaks).
    Path.symlink_to = original_symlink_to  # type: ignore[assignment]


def test_link_copy_path_falls_back_when_notimplementederror(
    store, workspace_root, monkeypatch
):
    """`NotImplementedError` is what older Pythons raised — also covered."""

    att = store.create(
        filename="oops.txt",
        mime_type="text/plain",
        content=b"x",
        scope="chatroom:r1",
        uploaded_by="user",
    )

    def _raise(self, *args, **kwargs):  # type: ignore[no-redef]
        raise NotImplementedError

    monkeypatch.setattr(Path, "symlink_to", _raise)

    target = link_attachment_to_workspace(att, workspace_root)
    assert target.read_bytes() == b"x"
