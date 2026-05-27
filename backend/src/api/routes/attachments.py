"""Attachment REST routes (Plan 3 Phase P3 Task 21).

Endpoints
---------
``POST /api/attachments?scope=...``
    Upload one file (``multipart/form-data``). Validates size + MIME prefix
    against ``config/system.yaml`` ``attachments`` section (with safe defaults
    if the section is missing). Returns the metadata record (no storage_path).

``GET /api/attachments``
    List metadata records, optionally filtered by ``scope``.

``GET /api/attachments/{id}``
    Get a single metadata record.

``GET /api/attachments/{id}/content``
    Stream raw bytes with the original MIME type.

``DELETE /api/attachments/{id}``
    Remove the file and its index entry.

The route uses a module-level ``AttachmentStore`` singleton + a settings
override dict so integration tests can swap them out cleanly without booting
the full FastAPI app or touching the YAML config.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from core.attachment import ATTACHMENTS_ROOT, AttachmentStore

from ..schemas import APIResponse


router = APIRouter(prefix="/api/attachments", tags=["attachments"])


# ----------------------------------------------------------------------- state

_store: Optional[AttachmentStore] = None
_settings_override: dict[str, Any] = {}


# Default guard rails. Mirror config/system.yaml ``attachments`` block.
_DEFAULT_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_DEFAULT_ALLOWED_MIME_PREFIXES: tuple[str, ...] = (
    "image/",
    "text/",
    "application/pdf",
    "application/json",
    "application/zip",
)


def set_attachment_store(store: Optional[AttachmentStore]) -> None:
    """Inject (or clear) the module-level store. For lifespan + tests."""

    global _store
    _store = store


def _get_store() -> AttachmentStore:
    global _store
    if _store is None:
        _store = AttachmentStore(root=ATTACHMENTS_ROOT)
    return _store


def _load_yaml_settings() -> dict[str, Any]:
    """Read the ``attachments`` block from ``config/system.yaml`` if present."""

    try:
        from core.config import _default_project_root, _load_yaml
    except Exception:
        return {}

    try:
        path = _default_project_root() / "config" / "system.yaml"
        raw = _load_yaml(path)
    except Exception:
        return {}
    block = raw.get("attachments") if isinstance(raw, dict) else None
    return block if isinstance(block, dict) else {}


def get_attachment_settings() -> dict[str, Any]:
    """Resolve attachment guards from override > YAML > defaults."""

    yaml_settings = _load_yaml_settings()
    max_size = _settings_override.get(
        "max_size_bytes",
        yaml_settings.get("max_size_bytes", _DEFAULT_MAX_SIZE_BYTES),
    )
    allowed = _settings_override.get(
        "allowed_mime_prefixes",
        yaml_settings.get("allowed_mime_prefixes", list(_DEFAULT_ALLOWED_MIME_PREFIXES)),
    )
    if not isinstance(allowed, (list, tuple)):
        allowed = list(_DEFAULT_ALLOWED_MIME_PREFIXES)
    try:
        max_size = int(max_size)
    except (TypeError, ValueError):
        max_size = _DEFAULT_MAX_SIZE_BYTES
    return {"max_size_bytes": max_size, "allowed_mime_prefixes": list(allowed)}


def _is_mime_allowed(mime_type: str, allowed_prefixes: list[str]) -> bool:
    if not allowed_prefixes:
        return True  # empty list = unrestricted
    mt = (mime_type or "").lower()
    return any(mt.startswith(p.lower()) for p in allowed_prefixes)


def _serialize(att) -> dict[str, Any]:
    """Public view of an Attachment record (no storage_path leak)."""

    return {
        "id": att.id,
        "filename": att.filename,
        "mime_type": att.mime_type,
        "size_bytes": att.size_bytes,
        "scope": att.scope,
        "uploaded_by": att.uploaded_by,
        "created_at": att.created_at.isoformat() if hasattr(att.created_at, "isoformat") else str(att.created_at),
        "meta": att.meta,
    }


# --------------------------------------------------------------------- routes


@router.post("", response_model=APIResponse)
async def upload_attachment(
    scope: str = Query(..., min_length=1, description="拥有者 scope，如 chatroom:<id> / chat_session:<id>"),
    uploaded_by: str = Query("user", description="上传方标识，默认 user"),
    file: UploadFile = File(...),
) -> APIResponse:
    """Upload a single file under the given ``scope``."""

    settings = get_attachment_settings()
    content = await file.read()
    if len(content) > settings["max_size_bytes"]:
        raise HTTPException(
            status_code=413,
            detail=f"file too large: {len(content)} bytes > limit {settings['max_size_bytes']} bytes",
        )

    mime_type = file.content_type or "application/octet-stream"
    if not _is_mime_allowed(mime_type, settings["allowed_mime_prefixes"]):
        raise HTTPException(
            status_code=415,
            detail=f"unsupported mime type: {mime_type}",
        )

    att = _get_store().create(
        filename=file.filename or "unnamed",
        mime_type=mime_type,
        content=content,
        scope=scope,
        uploaded_by=uploaded_by,
    )
    return APIResponse(status="ok", data=_serialize(att))


@router.get("", response_model=APIResponse)
async def list_attachments(scope: Optional[str] = Query(default=None)) -> APIResponse:
    rows = _get_store().list(scope=scope)
    return APIResponse(status="ok", data=[_serialize(r) for r in rows])


@router.get("/{attachment_id}", response_model=APIResponse)
async def get_attachment_metadata(attachment_id: str) -> APIResponse:
    att = _get_store().get(attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    return APIResponse(status="ok", data=_serialize(att))


@router.get("/{attachment_id}/content")
async def get_attachment_content(attachment_id: str) -> Response:
    from pathlib import Path

    att = _get_store().get(attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    p = Path(att.storage_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="attachment file missing on disk")
    headers = {
        "Content-Disposition": f'inline; filename="{att.filename}"',
    }
    return Response(content=p.read_bytes(), media_type=att.mime_type, headers=headers)


@router.delete("/{attachment_id}", response_model=APIResponse)
async def delete_attachment(attachment_id: str) -> APIResponse:
    if not _get_store().delete(attachment_id):
        raise HTTPException(status_code=404, detail="attachment not found")
    return APIResponse(status="ok")


__all__ = [
    "router",
    "set_attachment_store",
    "get_attachment_settings",
]
