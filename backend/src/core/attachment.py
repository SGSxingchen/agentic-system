"""Attachment store with disk persistence (Plan 3 Phase P3 Task 20).

Provides simple, append-only attachment storage rooted at ``data/attachments``.
Each attachment is written under a per-scope directory derived from a SHA-1
hash of the scope string, so the layout stays bounded and avoids leaking the
raw scope into the filesystem.

Index metadata lives in ``<root>/_index.json`` and is rewritten atomically on
every mutation. The index records the original filename, MIME type, size in
bytes, on-disk path, creation timestamp, uploader, scope and a free-form meta
dict.

The store is intentionally minimal — no streaming, no chunking, no concurrent
writers. It is a building block for the REST API in Task 21.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


ATTACHMENTS_ROOT = Path("data/attachments")


@dataclass
class Attachment:
    """Metadata record for a single uploaded attachment."""

    id: str
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    created_at: datetime
    uploaded_by: str
    scope: str
    meta: dict = field(default_factory=dict)


def _sanitize_basename(filename: str) -> str:
    """Sanitize ``filename`` so it is safe to use as a path segment.

    Strips path separators and unsafe characters, keeps a small set of
    visible glyphs and truncates to 80 chars to avoid OS path limits.
    """

    cleaned = "".join(c for c in filename if c.isalnum() or c in "._-")
    cleaned = cleaned.lstrip(".")  # avoid hidden files / "..".
    return cleaned[:80] or "file"


class AttachmentStore:
    """Filesystem-backed attachment store with a flat JSON index."""

    def __init__(self, root: Path | str = ATTACHMENTS_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "_index.json"
        self.index: dict[str, dict[str, Any]] = self._load_index()

    # ------------------------------------------------------------------ index

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # Corrupt index: start fresh but keep the broken file as a
                # sibling so a human can inspect it.
                backup = self.index_path.with_suffix(".broken.json")
                self.index_path.replace(backup)
                return {}
        return {}

    def _save_index(self) -> None:
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.index, default=str, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.index_path)

    # ----------------------------------------------------------------- mutation

    def create(
        self,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
        scope: str,
        uploaded_by: str,
        meta: Optional[dict] = None,
    ) -> Attachment:
        """Persist ``content`` under ``scope`` and return the metadata record."""

        att_id = str(uuid.uuid4())
        scope_hash = hashlib.sha1(scope.encode("utf-8")).hexdigest()[:12]
        scope_dir = self.root / scope_hash
        scope_dir.mkdir(parents=True, exist_ok=True)

        safe = _sanitize_basename(filename)
        path = scope_dir / f"{att_id}__{safe}"
        path.write_bytes(content)

        att = Attachment(
            id=att_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            storage_path=str(path),
            created_at=datetime.utcnow(),
            uploaded_by=uploaded_by,
            scope=scope,
            meta=dict(meta or {}),
        )
        self.index[att_id] = asdict(att)
        self._save_index()
        return att

    def delete(self, att_id: str) -> bool:
        """Remove the attachment file and its index entry. Idempotent."""

        record = self.index.get(att_id)
        if not record:
            return False
        try:
            Path(record["storage_path"]).unlink(missing_ok=True)
        except OSError:
            # Even if file removal fails, drop the index entry so we don't
            # leak ghost references; the orphan blob can be cleaned manually.
            pass
        del self.index[att_id]
        self._save_index()
        return True

    # ------------------------------------------------------------------ query

    def get(self, att_id: str) -> Optional[Attachment]:
        record = self.index.get(att_id)
        if not record:
            return None
        return self._record_to_attachment(record)

    def list(self, *, scope: Optional[str] = None) -> list[Attachment]:
        records = self.index.values()
        if scope is not None:
            records = [r for r in records if r.get("scope") == scope]
        return [self._record_to_attachment(r) for r in records]

    @staticmethod
    def _record_to_attachment(record: dict[str, Any]) -> Attachment:
        created_at = record.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = datetime.utcnow()
        elif created_at is None:
            created_at = datetime.utcnow()
        return Attachment(
            id=record["id"],
            filename=record["filename"],
            mime_type=record["mime_type"],
            size_bytes=int(record["size_bytes"]),
            storage_path=record["storage_path"],
            created_at=created_at,
            uploaded_by=record.get("uploaded_by", ""),
            scope=record.get("scope", ""),
            meta=dict(record.get("meta") or {}),
        )


__all__ = ["Attachment", "AttachmentStore", "ATTACHMENTS_ROOT"]
