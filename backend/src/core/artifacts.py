"""File-backed artifact storage for frontend previews and downloads."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "data" / "artifacts"
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/typescript",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    "image/svg+xml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_filename(value: str, fallback: str = "artifact") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in value.strip())
    cleaned = cleaned.strip(" .")
    return cleaned[:120] or fallback


def is_text_mime(mime_type: str) -> bool:
    clean = (mime_type or "").split(";", 1)[0].lower()
    return clean.startswith(TEXT_MIME_PREFIXES) or clean in TEXT_MIME_TYPES


class ArtifactStore:
    """Small JSON manifest + file storage for generated frontend artifacts."""

    def __init__(self, root: Optional[str | Path] = None) -> None:
        configured = root or os.getenv("ARTIFACT_STORE_DIR") or DEFAULT_ARTIFACT_ROOT
        self.root = Path(configured)
        self.files_dir = self.root / "files"
        self.manifest_path = self.root / "artifacts.json"

    def list_artifacts(
        self,
        *,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        data = self._read_manifest()
        artifacts = data["artifacts"]
        if session_id:
            artifacts = [item for item in artifacts if item.get("session_id") == session_id]
        artifacts.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
        return deepcopy(artifacts[: max(1, min(limit, 200))])

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        data = self._read_manifest()
        artifact = self._find(data, artifact_id)
        return deepcopy(artifact) if artifact else None

    def get_file_path(self, artifact: Dict[str, Any]) -> Path:
        return (self.files_dir / str(artifact["id"]) / str(artifact["stored_filename"])).resolve()

    def read_text(self, artifact_id: str, max_chars: int = 200000) -> Optional[str]:
        artifact = self.get_artifact(artifact_id)
        if not artifact or not artifact.get("previewable"):
            return None
        path = self.get_file_path(artifact)
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding=artifact.get("encoding") or "utf-8", errors="replace")[:max_chars]

    def create_artifact(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        mime_type: str = "",
        filename: str = "",
        encoding: str = "utf-8",
        content_encoding: str = "text",
        session_id: Optional[str] = None,
        message_id: Optional[str] = None,
        source: str = "api",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        kind = (kind or "file").lower()
        if kind not in {"html", "markdown", "code", "image", "file", "text"}:
            kind = "file"

        artifact_id = uuid.uuid4().hex
        ext = self._default_extension(kind, mime_type)
        stored_filename = safe_filename(filename or f"{kind}-{artifact_id[:8]}{ext}")
        guessed_mime = mime_type or mimetypes.guess_type(stored_filename)[0] or self._mime_for_kind(kind)

        if content_encoding == "base64":
            raw = base64.b64decode(content, validate=True)
        else:
            raw = content.encode(encoding or "utf-8")

        now = utc_now()
        previewable = kind in {"html", "markdown", "code", "text", "image"} or is_text_mime(guessed_mime)
        artifact = {
            "id": artifact_id,
            "kind": kind,
            "title": title.strip() if title and title.strip() else stored_filename,
            "filename": stored_filename,
            "stored_filename": stored_filename,
            "mime_type": guessed_mime,
            "size": len(raw),
            "encoding": encoding or "utf-8",
            "previewable": previewable,
            "session_id": session_id,
            "message_id": message_id,
            "source": source,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
            "download_url": f"/api/artifacts/{artifact_id}/download",
            "open_url": f"/api/artifacts/{artifact_id}/open",
            "content_url": f"/api/artifacts/{artifact_id}/content",
        }

        data = self._read_manifest()
        target_dir = self.files_dir / artifact_id
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / stored_filename).write_bytes(raw)
        data["artifacts"].append(artifact)
        self._write_manifest(data)
        return deepcopy(artifact)

    def delete_artifact(self, artifact_id: str) -> bool:
        data = self._read_manifest()
        before = len(data["artifacts"])
        data["artifacts"] = [item for item in data["artifacts"] if str(item.get("id")) != artifact_id]
        if len(data["artifacts"]) == before:
            return False
        self._write_manifest(data)
        artifact_dir = self.files_dir / artifact_id
        if artifact_dir.exists():
            for child in artifact_dir.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
            artifact_dir.rmdir()
        return True

    def _read_manifest(self) -> Dict[str, Any]:
        if not self.manifest_path.exists():
            return {"artifacts": []}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"artifacts": []}
        if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
            return {"artifacts": []}
        return {"artifacts": [self._normalize(item) for item in data["artifacts"] if isinstance(item, dict) and item.get("id")]}

    def _write_manifest(self, data: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            temp_name = file.name
        os.replace(temp_name, self.manifest_path)

    def _find(self, data: Dict[str, Any], artifact_id: str) -> Optional[Dict[str, Any]]:
        return next((item for item in data["artifacts"] if str(item.get("id")) == artifact_id), None)

    def _normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        now = utc_now()
        artifact_id = str(raw["id"])
        filename = safe_filename(str(raw.get("filename") or raw.get("stored_filename") or artifact_id))
        mime_type = str(raw.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
        return {
            "id": artifact_id,
            "kind": str(raw.get("kind") or "file"),
            "title": str(raw.get("title") or filename),
            "filename": filename,
            "stored_filename": safe_filename(str(raw.get("stored_filename") or filename)),
            "mime_type": mime_type,
            "size": int(raw.get("size") or 0),
            "encoding": str(raw.get("encoding") or "utf-8"),
            "previewable": bool(raw.get("previewable", is_text_mime(mime_type))),
            "session_id": raw.get("session_id"),
            "message_id": raw.get("message_id"),
            "source": str(raw.get("source") or "api"),
            "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            "created_at": str(raw.get("created_at") or now),
            "updated_at": str(raw.get("updated_at") or raw.get("created_at") or now),
            "download_url": str(raw.get("download_url") or f"/api/artifacts/{artifact_id}/download"),
            "open_url": str(raw.get("open_url") or f"/api/artifacts/{artifact_id}/open"),
            "content_url": str(raw.get("content_url") or f"/api/artifacts/{artifact_id}/content"),
        }

    def _mime_for_kind(self, kind: str) -> str:
        return {
            "html": "text/html",
            "markdown": "text/markdown",
            "code": "text/plain",
            "text": "text/plain",
            "image": "image/png",
        }.get(kind, "application/octet-stream")

    def _default_extension(self, kind: str, mime_type: str) -> str:
        if kind == "html":
            return ".html"
        if kind == "markdown":
            return ".md"
        if kind in {"code", "text"}:
            return ".txt"
        if kind == "image" and mime_type:
            return mimetypes.guess_extension(mime_type.split(";", 1)[0]) or ""
        return ""
