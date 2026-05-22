"""工作区管理路由

工作区是用户导入的项目目录（类似 ChatGPT Project / Claude Project），由系统持久化在
``workspace/projects/{id}/`` 下。每个工作区有独立的元数据文件 ``.workspace.json`` 与
项目文件根目录 ``root/``。

端点:
- GET    /api/workspaces                          列出工作区
- GET    /api/workspaces/{id}                     工作区详情（带顶层文件清单）
- POST   /api/workspaces/import                   ZIP 压缩包导入
- DELETE /api/workspaces/{id}                     删除工作区
- GET    /api/workspaces/{id}/files?path=         列出指定子目录
- GET    /api/workspaces/{id}/files/content?path= 读取文本文件内容
- PUT    /api/workspaces/{id}/files/content       保存文本文件内容
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..schemas import APIResponse
from core.workspace import workspace_path

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ─── 常量 ─────────────────────────────────────────────

PROJECTS_DIR = "projects"
META_FILENAME = ".workspace.json"

MAX_ZIP_BYTES = 200 * 1024 * 1024  # 单个上传 zip 最大 200 MB
MAX_FILE_BYTES_FOR_EDIT = 1 * 1024 * 1024  # 1 MB 以上文件视为不可在线编辑
MAX_TEXT_DETECT_BYTES = 256 * 1024  # 探测是否文本时只读前 256 KB
TEXT_BINARY_RATIO_THRESHOLD = 0.20  # 不可打印字符占比超过此值视为二进制


# ─── 工具函数 ─────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return cleaned[:64]


def _projects_root() -> Path:
    return workspace_path(PROJECTS_DIR, create=True)


def _workspace_dir(workspace_id: str) -> Path:
    safe = _safe_id(workspace_id)
    if not safe:
        raise HTTPException(status_code=400, detail="工作区 ID 非法")
    return _projects_root() / safe


def _workspace_root(workspace_id: str) -> Path:
    return _workspace_dir(workspace_id) / "root"


def _meta_path(workspace_id: str) -> Path:
    return _workspace_dir(workspace_id) / META_FILENAME


def _load_meta(workspace_id: str) -> Optional[Dict[str, Any]]:
    path = _meta_path(workspace_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_meta(workspace_id: str, meta: Dict[str, Any]) -> None:
    path = _meta_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize_root(root: Path) -> Tuple[int, int, int]:
    """Return (file_count, dir_count, total_bytes) recursively under root."""
    if not root.exists():
        return 0, 0, 0
    file_count = 0
    dir_count = 0
    total_bytes = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_dir():
                dir_count += 1
            elif entry.is_file():
                file_count += 1
                total_bytes += entry.stat().st_size
        except OSError:
            continue
    return file_count, dir_count, total_bytes


def _list_dir(root: Path, sub_path: str = "", limit: int = 500) -> List[Dict[str, Any]]:
    target = _resolve_inside(root, sub_path)
    if not target.exists() or not target.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
        try:
            stat = entry.stat()
        except OSError:
            continue
        rel = entry.relative_to(root).as_posix()
        items.append(
            {
                "path": rel,
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": int(stat.st_size) if entry.is_file() else None,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
        )
        if len(items) >= limit:
            break
    return items


def _resolve_inside(root: Path, sub_path: str) -> Path:
    """Resolve a relative path inside root. Reject .. escape attempts."""
    cleaned = (sub_path or "").strip().lstrip("/\\")
    if any(part == ".." for part in cleaned.replace("\\", "/").split("/")):
        raise HTTPException(status_code=400, detail="路径不安全：包含 .. 段")
    candidate = (root / cleaned).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不安全：超出工作区根目录")
    return candidate


def _sniff_text(data: bytes) -> Tuple[bool, str]:
    """Return (is_text, encoding)."""
    if not data:
        return True, "utf-8"
    sample = data[:MAX_TEXT_DETECT_BYTES]

    # Heuristic 1: NUL byte → almost certainly binary
    if b"\x00" in sample:
        return False, ""

    # Heuristic 2: try UTF-8 first, then GBK; otherwise binary
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            sample.decode(encoding)
            # decoded — also check ratio of control characters
            decoded = sample.decode(encoding, errors="ignore")
            non_print = sum(1 for ch in decoded if ord(ch) < 0x20 and ch not in "\r\n\t")
            ratio = non_print / max(len(decoded), 1)
            if ratio > TEXT_BINARY_RATIO_THRESHOLD:
                return False, encoding
            return True, encoding
        except UnicodeDecodeError:
            continue
    return False, ""


def _meta_to_response(meta: Dict[str, Any], *, include_files: bool = False) -> Dict[str, Any]:
    workspace_id = meta.get("id", "")
    root = _workspace_root(workspace_id)
    file_count, dir_count, total_bytes = _summarize_root(root)
    payload: Dict[str, Any] = {
        "id": workspace_id,
        "name": meta.get("name") or workspace_id,
        "kind": meta.get("kind", "managed"),
        "source": meta.get("source", "upload"),
        "root_path": str(root),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "metadata": {
            "description": meta.get("description") or "",
            "file_count": file_count,
            "directory_count": dir_count,
            "total_bytes": total_bytes,
            **(meta.get("metadata") or {}),
        },
    }
    if include_files:
        payload["files"] = _list_dir(root, "", limit=200)
    return payload


# ─── 端点 ─────────────────────────────────────────────


@router.get("", response_model=APIResponse)
async def list_workspaces():
    """列出已管理的工作区。"""
    root = _projects_root()
    items: List[Dict[str, Any]] = []
    if root.exists():
        for entry in sorted(root.iterdir(), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            meta = _load_meta(entry.name)
            if not meta:
                continue
            items.append(_meta_to_response(meta, include_files=False))
    items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return APIResponse(status="ok", data=items)


@router.get("/{workspace_id}", response_model=APIResponse)
async def get_workspace(workspace_id: str):
    """查看工作区详情，包含顶层文件清单。"""
    meta = _load_meta(_safe_id(workspace_id))
    if not meta:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return APIResponse(status="ok", data=_meta_to_response(meta, include_files=True))


@router.post("/import", response_model=APIResponse)
async def import_workspace(
    file: UploadFile = File(...),
    name: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
):
    """导入 ZIP 压缩包为工作区。"""
    raw = await file.read()
    if not raw:
        return APIResponse(status="error", message="导入失败：上传内容为空")
    if len(raw) > MAX_ZIP_BYTES:
        return APIResponse(status="error", message=f"导入失败：压缩包超过 {MAX_ZIP_BYTES // (1024 * 1024)} MB 上限")

    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        return APIResponse(status="error", message="导入失败：仅支持 .zip 压缩包")

    workspace_id = uuid.uuid4().hex[:12]
    workspace_dir = _workspace_dir(workspace_id)
    root_dir = _workspace_root(workspace_id)
    root_dir.mkdir(parents=True, exist_ok=True)

    try:
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for member in zf.infolist():
                member_name = member.filename
                if not member_name:
                    continue
                normalized = member_name.replace("\\", "/")
                if normalized.startswith("/") or ".." in normalized.split("/"):
                    raise HTTPException(status_code=400, detail="导入失败：压缩包包含不安全路径")
                target = (root_dir / normalized).resolve()
                try:
                    target.relative_to(root_dir.resolve())
                except ValueError:
                    raise HTTPException(status_code=400, detail="导入失败：压缩包包含越界路径")

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, open(target, "wb") as dest:
                    shutil.copyfileobj(source, dest)
    except HTTPException:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        raise
    except zipfile.BadZipFile:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        return APIResponse(status="error", message="导入失败：压缩包格式无效")
    except Exception as exc:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        return APIResponse(status="error", message=f"导入失败：{exc}")

    display_name = (name or "").strip() or Path(file.filename or "workspace").stem
    now = _now_iso()
    meta = {
        "id": workspace_id,
        "name": display_name,
        "kind": "managed",
        "source": "zip_upload",
        "description": (description or "").strip(),
        "created_at": now,
        "updated_at": now,
        "metadata": {
            "original_filename": file.filename,
            "imported_bytes": len(raw),
        },
    }
    _save_meta(workspace_id, meta)
    return APIResponse(status="ok", message="工作区已导入", data=_meta_to_response(meta, include_files=True))


@router.delete("/{workspace_id}", response_model=APIResponse)
async def delete_workspace(workspace_id: str):
    """删除工作区。"""
    meta = _load_meta(_safe_id(workspace_id))
    if not meta:
        raise HTTPException(status_code=404, detail="工作区不存在")
    workspace_dir = _workspace_dir(workspace_id)
    shutil.rmtree(workspace_dir, ignore_errors=True)
    return APIResponse(status="ok", message="工作区已删除", data={"id": workspace_id})


# ─── 文件 API ─────────────────────────────────────────


@router.get("/{workspace_id}/files", response_model=APIResponse)
async def list_workspace_files(workspace_id: str, path: str = Query(default="")):
    """按目录列出工作区文件。"""
    meta = _load_meta(_safe_id(workspace_id))
    if not meta:
        raise HTTPException(status_code=404, detail="工作区不存在")
    root = _workspace_root(workspace_id)
    files = _list_dir(root, path, limit=500)
    return APIResponse(
        status="ok",
        data={
            "workspace_id": workspace_id,
            "path": path,
            "files": files,
        },
    )


@router.get("/{workspace_id}/files/content", response_model=APIResponse)
async def get_workspace_file_content(workspace_id: str, path: str = Query(...)):
    """读取文本文件内容。"""
    meta = _load_meta(_safe_id(workspace_id))
    if not meta:
        raise HTTPException(status_code=404, detail="工作区不存在")
    root = _workspace_root(workspace_id)
    target = _resolve_inside(root, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    size = target.stat().st_size
    raw = target.read_bytes()
    is_text, encoding = _sniff_text(raw)
    too_large = size > MAX_FILE_BYTES_FOR_EDIT
    editable = bool(is_text and not too_large)

    payload: Dict[str, Any] = {
        "workspace_id": workspace_id,
        "path": path,
        "size": size,
        "editable": editable,
        "is_text": is_text,
        "encoding": encoding,
        "too_large": too_large,
        "max_editable_bytes": MAX_FILE_BYTES_FOR_EDIT,
    }
    if editable:
        payload["content"] = raw.decode(encoding or "utf-8", errors="replace")
    elif is_text and too_large:
        payload["content"] = raw[:MAX_FILE_BYTES_FOR_EDIT].decode(encoding or "utf-8", errors="replace")
        payload["truncated"] = True
    else:
        payload["content"] = ""
        payload["binary"] = True
    return APIResponse(status="ok", data=payload)


class WorkspaceFileSaveRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = Field(default="")
    encoding: str = Field(default="utf-8")
    create_parents: bool = Field(default=True)


@router.put("/{workspace_id}/files/content", response_model=APIResponse)
async def save_workspace_file_content(workspace_id: str, req: WorkspaceFileSaveRequest):
    """保存文本文件内容。"""
    meta = _load_meta(_safe_id(workspace_id))
    if not meta:
        raise HTTPException(status_code=404, detail="工作区不存在")
    root = _workspace_root(workspace_id)
    target = _resolve_inside(root, req.path)

    encoding = (req.encoding or "utf-8").strip() or "utf-8"
    encoded = req.content.encode(encoding, errors="replace")
    if len(encoded) > MAX_FILE_BYTES_FOR_EDIT:
        return APIResponse(status="error", message="保存失败：单文件不可超过 1 MB")

    if target.exists() and target.is_dir():
        return APIResponse(status="error", message="保存失败：目标是目录")
    if not target.parent.exists():
        if not req.create_parents:
            return APIResponse(status="error", message="保存失败：父目录不存在")
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_bytes(encoded)

    meta["updated_at"] = _now_iso()
    _save_meta(workspace_id, meta)

    stat = target.stat()
    return APIResponse(
        status="ok",
        message="文件已保存",
        data={
            "workspace_id": workspace_id,
            "path": req.path,
            "size": int(stat.st_size),
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
        },
    )


__all__ = ["router"]
