"""Managed workspace APIs."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from core.workspace import (
    MAX_ZIP_BYTES,
    WorkspaceFileError,
    WorkspaceImportError,
    WorkspaceNotFoundError,
    WorkspaceStore,
)

from ..schemas import APIResponse, WorkspaceFileContentUpdateRequest

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

MAX_MULTIPART_BODY_BYTES = MAX_ZIP_BYTES + 1024 * 1024


@dataclass
class _MultipartUpload:
    filename: str
    content: bytes


def _workspace_store() -> WorkspaceStore:
    return WorkspaceStore()


@router.get("", response_model=APIResponse)
async def list_workspaces() -> APIResponse:
    """List registered managed workspaces."""

    workspaces = [workspace.to_dict() for workspace in _workspace_store().list()]
    return APIResponse(status="ok", data=workspaces)


@router.get("/{workspace_id}", response_model=APIResponse)
async def get_workspace(
    workspace_id: str,
    depth: int = Query(default=2, ge=0, le=20),
    limit: int = Query(default=200, ge=1, le=2000),
    include_files: bool = Query(default=True),
) -> APIResponse:
    """Return one workspace and, by default, a shallow file listing."""

    store = _workspace_store()
    try:
        workspace = store.get(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="workspace not found") from None

    payload = workspace.to_dict()
    if include_files:
        files, truncated = store.list_files(workspace.id, depth=depth, limit=limit)
        payload["files"] = files
        payload["files_truncated"] = truncated
    return APIResponse(status="ok", data=payload)


@router.delete("/{workspace_id}", response_model=APIResponse)
async def delete_workspace(workspace_id: str) -> APIResponse:
    """Delete a managed project workspace."""

    try:
        workspace = _workspace_store().delete(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="workspace not found") from None
    except WorkspaceFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return APIResponse(status="ok", message="工作区已删除", data={"id": workspace.id})


@router.get("/{workspace_id}/files", response_model=APIResponse)
async def list_workspace_files(
    workspace_id: str,
    path: str = Query(default=""),
    depth: int = Query(default=1, ge=0, le=20),
    limit: int = Query(default=500, ge=1, le=2000),
) -> APIResponse:
    """List files below a workspace-relative directory."""

    try:
        files, truncated = _workspace_store().list_files(
            workspace_id,
            base_path=path,
            depth=depth,
            limit=limit,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="workspace not found") from None
    except WorkspaceFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return APIResponse(
        status="ok",
        data={
            "workspace_id": workspace_id,
            "path": path,
            "files": files,
            "files_truncated": truncated,
        },
    )


@router.get("/{workspace_id}/files/content", response_model=APIResponse)
async def read_workspace_file(
    workspace_id: str,
    path: str = Query(..., min_length=1),
    encoding: str = Query(default="utf-8"),
) -> APIResponse:
    """Read a workspace text file for manual inspection/editing."""

    try:
        file_content = _workspace_store().read_text_file(
            workspace_id,
            path,
            encoding=encoding,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="workspace not found") from None
    except WorkspaceFileError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from None

    return APIResponse(status="ok", data={"workspace_id": workspace_id, **file_content})


@router.put("/{workspace_id}/files/content", response_model=APIResponse)
async def write_workspace_file(
    workspace_id: str,
    req: WorkspaceFileContentUpdateRequest,
) -> APIResponse:
    """Save a workspace text file after manual editing."""

    try:
        file_content = _workspace_store().write_text_file(
            workspace_id,
            req.path,
            req.content,
            encoding=req.encoding,
        )
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="workspace not found") from None
    except WorkspaceFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return APIResponse(status="ok", data={"workspace_id": workspace_id, **file_content})


@router.post("/import", response_model=APIResponse)
async def import_workspace(request: Request) -> APIResponse:
    """Import a zip upload as a managed project workspace."""

    fields, upload = await _parse_multipart_request(request)
    if upload is None:
        raise HTTPException(status_code=400, detail="multipart field 'file' is required")
    if len(upload.content) > MAX_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="uploaded zip file is too large")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as file:
            file.write(upload.content)
            temp_path = Path(file.name)

        workspace = _workspace_store().import_zip(
            temp_path,
            original_filename=upload.filename,
            name=fields.get("name"),
            description=fields.get("description"),
        )
    except WorkspaceImportError as exc:
        status_code = 413 if "too large" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return APIResponse(status="ok", data=workspace.to_dict())


async def _parse_multipart_request(request: Request) -> tuple[dict[str, str], _MultipartUpload | None]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="multipart/form-data is required")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_MULTIPART_BODY_BYTES:
                raise HTTPException(status_code=413, detail="multipart body is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid content-length") from None

    body = await request.body()
    if len(body) > MAX_MULTIPART_BODY_BYTES:
        raise HTTPException(status_code=413, detail="multipart body is too large")

    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=400, detail="invalid multipart body")

    fields: dict[str, str] = {}
    upload: _MultipartUpload | None = None
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        if not field_name:
            continue

        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if field_name == "file" and filename is not None:
            upload = _MultipartUpload(filename=_clean_filename(filename), content=payload)
            continue

        fields[field_name] = _decode_text_part(part, payload)

    return fields, upload


def _clean_filename(filename: str) -> str:
    cleaned = filename.replace("\\", "/").split("/")[-1].strip()
    if not cleaned or "\x00" in cleaned:
        return "workspace.zip"
    return cleaned


def _decode_text_part(part: Any, payload: bytes) -> str:
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset).strip()
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace").strip()
