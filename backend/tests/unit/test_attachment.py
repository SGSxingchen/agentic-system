"""Unit tests for ``core.attachment`` (B1 — Plan 3 Phase P3 Task 20)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Same convention as the other unit tests: prepend ``backend/src``.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.attachment import Attachment, AttachmentStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return AttachmentStore(root=tmp_path)


def test_attachment_create_writes_file_and_meta(store):
    att = store.create(
        filename="hello.txt",
        mime_type="text/plain",
        content=b"hi there",
        scope="chatroom:r1",
        uploaded_by="user",
    )
    assert att.id
    assert att.size_bytes == 8
    assert att.filename == "hello.txt"
    assert att.mime_type == "text/plain"
    assert att.scope == "chatroom:r1"
    assert att.uploaded_by == "user"
    p = Path(att.storage_path)
    assert p.exists()
    assert p.read_bytes() == b"hi there"


def test_attachment_list_by_scope(store):
    store.create(
        filename="a.txt",
        mime_type="text/plain",
        content=b"a",
        scope="chat_session:s1",
        uploaded_by="user",
    )
    store.create(
        filename="b.txt",
        mime_type="text/plain",
        content=b"b",
        scope="chatroom:r2",
        uploaded_by="user",
    )
    rows = store.list(scope="chat_session:s1")
    assert len(rows) == 1
    assert rows[0].filename == "a.txt"

    all_rows = store.list()
    assert len(all_rows) == 2


def test_attachment_get_returns_record(store):
    att = store.create(
        filename="x.txt",
        mime_type="text/plain",
        content=b"x",
        scope="chatroom:r3",
        uploaded_by="user",
    )
    got = store.get(att.id)
    assert got is not None
    assert got.id == att.id
    assert got.filename == "x.txt"
    assert store.get("nope") is None


def test_attachment_delete_removes_file(store):
    att = store.create(
        filename="x.txt",
        mime_type="text/plain",
        content=b"x",
        scope="chatroom:r3",
        uploaded_by="user",
    )
    assert Path(att.storage_path).exists()
    deleted = store.delete(att.id)
    assert deleted is True
    assert not Path(att.storage_path).exists()
    assert store.get(att.id) is None
    assert store.delete(att.id) is False  # idempotent


def test_attachment_index_persisted_across_instances(tmp_path):
    s1 = AttachmentStore(root=tmp_path)
    att = s1.create(
        filename="persist.txt",
        mime_type="text/plain",
        content=b"keep",
        scope="chatroom:r4",
        uploaded_by="user",
    )
    # New instance should re-load index from disk.
    s2 = AttachmentStore(root=tmp_path)
    got = s2.get(att.id)
    assert got is not None
    assert got.filename == "persist.txt"


def test_attachment_filename_sanitized(store):
    att = store.create(
        filename="../../../evil name with spaces.txt",
        mime_type="text/plain",
        content=b"x",
        scope="chatroom:rX",
        uploaded_by="user",
    )
    # storage_path basename must not contain path traversal or spaces.
    base = Path(att.storage_path).name
    assert ".." not in base
    assert "/" not in base
    assert "\\" not in base
    # original filename preserved in metadata.
    assert att.filename == "../../../evil name with spaces.txt"


def test_attachment_meta_default_empty(store):
    att = store.create(
        filename="m.txt",
        mime_type="text/plain",
        content=b"m",
        scope="chatroom:rM",
        uploaded_by="user",
    )
    assert att.meta == {}

    att2 = store.create(
        filename="m2.txt",
        mime_type="text/plain",
        content=b"m",
        scope="chatroom:rM",
        uploaded_by="user",
        meta={"source": "paste"},
    )
    assert att2.meta == {"source": "paste"}


def test_attachment_dataclass_shape():
    """Attachment should be a dataclass with the expected fields."""
    fields = {"id", "filename", "mime_type", "size_bytes", "storage_path",
              "created_at", "uploaded_by", "scope", "meta"}
    assert fields.issubset({f.name for f in Attachment.__dataclass_fields__.values()})
