"""Project workspace path helpers.

The runtime has two distinct roots:

- project root: repository/config/documentation location;
- workspace root: default mutable working directory for agent tools and
  generated runtime artifacts.

All relative workspace-style configuration is resolved against the project
root, never the current process cwd.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional


DEFAULT_WORKSPACE_DIR = "workspace"
MANAGED_PROJECTS_DIR = "projects"
WORKSPACE_REGISTRY_FILE = "_registry.json"
WORKSPACE_MANIFEST_FILE = ".agentic-workspace.json"
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_ZIP_FILE_BYTES = 50 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 250 * 1024 * 1024
MAX_ZIP_FILE_COUNT = 5000
MAX_ZIP_MEMBER_NAME_LENGTH = 4096
MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def project_root() -> Path:
    """Return the repository/project root."""

    return Path(__file__).resolve().parents[3]


def resolve_project_path(raw_path: str | Path, default: Optional[str | Path] = None) -> Path:
    """Resolve a path against the project root when it is relative."""

    value: str | Path | None = raw_path
    if value is None or not str(value).strip():
        value = default
    if value is None or not str(value).strip():
        raise ValueError("path is required")

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root() / path
    return path.resolve()


def default_workspace_root() -> Path:
    """Return the default mutable workspace root: ``<project>/workspace``."""

    return project_root() / DEFAULT_WORKSPACE_DIR


def resolve_workspace_root(
    configured: Optional[str | Path] = None,
    *,
    create: bool = True,
) -> Path:
    """Resolve and optionally create the workspace root.

    Empty/blank values mean the canonical default ``./workspace``. Explicit
    values are preserved, but relative values still resolve from project root
    for process-cwd independent behavior.
    """

    root = resolve_project_path(configured or "", default=DEFAULT_WORKSPACE_DIR)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_path(*parts: str, create: bool = False) -> Path:
    """Return a path under the default workspace root."""

    path = default_workspace_root().joinpath(*parts).resolve()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def session_workspace_slug(session_id: str | None) -> str:
    """Return a stable filesystem-safe slug for one chat session."""

    return safe_workspace_id(session_id, fallback="session")


def session_workspace_id(session_id: str | None) -> str:
    """Return the public workspace id used for an isolated chat session."""

    return f"session-{session_workspace_slug(session_id)}"


def session_workspace_root(session_id: str | None, *, create: bool = True) -> Path:
    """Return the mutable workspace root for one isolated chat session."""

    return workspace_path("sessions", session_workspace_slug(session_id), create=create)


class WorkspaceImportError(ValueError):
    """Raised when an uploaded workspace archive is invalid or unsafe."""


class WorkspaceNotFoundError(KeyError):
    """Raised when a managed workspace id is unknown."""


class WorkspaceFileError(ValueError):
    """Raised when a workspace file operation is invalid or unsafe."""


@dataclass
class ManagedWorkspace:
    """A registered project-style workspace managed by the backend."""

    id: str
    name: str
    kind: str
    source: str
    root_path: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_workspace_id(value: str | None, *, fallback: str = "workspace") -> str:
    """Return a path-safe id derived from a human name or filename."""

    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", ascii_value).strip(".-_").lower()
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    fallback_clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", fallback).strip(".-_").lower()
    return (cleaned or fallback_clean or "workspace")[:80]


def managed_projects_root(*, create: bool = True) -> Path:
    """Return the root for imported project workspaces."""

    return workspace_path(MANAGED_PROJECTS_DIR, create=create)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_zip_member_path(raw_name: str) -> Path:
    if not raw_name or "\x00" in raw_name:
        raise WorkspaceImportError("zip contains an empty or invalid path")

    normalized = raw_name.replace("\\", "/")
    if len(normalized) > MAX_ZIP_MEMBER_NAME_LENGTH:
        raise WorkspaceImportError(f"zip path is too long: {raw_name}")
    if normalized.startswith("/") or normalized.startswith("//") or re.match(r"^[A-Za-z]:", normalized):
        raise WorkspaceImportError(f"zip contains an absolute path: {raw_name}")

    parts = PurePosixPath(normalized).parts
    if not parts:
        raise WorkspaceImportError("zip contains an empty path")

    for part in parts:
        if part in {"", ".", ".."}:
            raise WorkspaceImportError(f"zip contains an unsafe path: {raw_name}")
        if ":" in part:
            raise WorkspaceImportError(f"zip contains a dangerous path segment: {raw_name}")
        if len(part) > 255:
            raise WorkspaceImportError(f"zip path segment is too long: {raw_name}")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise WorkspaceImportError(f"zip contains a reserved Windows path: {raw_name}")

    return Path(*parts)


def _validate_zip_info(info: zipfile.ZipInfo) -> Path:
    if stat.S_ISLNK(info.external_attr >> 16):
        raise WorkspaceImportError(f"zip contains a symlink: {info.filename}")
    if info.file_size > MAX_ZIP_FILE_BYTES:
        raise WorkspaceImportError(f"zip member is too large: {info.filename}")
    return _safe_zip_member_path(info.filename)


def _safe_workspace_relative_path(raw_path: str | os.PathLike[str]) -> Path:
    normalized = str(raw_path or "").replace("\\", "/").strip()
    if not normalized:
        raise WorkspaceFileError("path is required")
    if "\x00" in normalized:
        raise WorkspaceFileError("path contains an invalid character")
    if normalized.startswith("/") or normalized.startswith("//") or re.match(r"^[A-Za-z]:", normalized):
        raise WorkspaceFileError("path must be relative to the workspace")

    parts = PurePosixPath(normalized).parts
    if not parts:
        raise WorkspaceFileError("path is required")
    for part in parts:
        if part in {"", ".", ".."}:
            raise WorkspaceFileError("path contains an unsafe segment")
        if ":" in part:
            raise WorkspaceFileError("path contains a dangerous segment")
        if len(part) > 255:
            raise WorkspaceFileError("path segment is too long")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise WorkspaceFileError("path contains a reserved Windows segment")
        if part == WORKSPACE_MANIFEST_FILE:
            raise WorkspaceFileError("workspace manifest is not editable")

    return Path(*parts)


def _normalize_text_encoding(encoding: str) -> str:
    cleaned = str(encoding or "utf-8").strip().lower().replace("_", "-")
    if cleaned in {"utf8", "utf-8"}:
        return "utf-8"
    if cleaned == "utf-8-sig":
        return "utf-8-sig"
    raise WorkspaceFileError("only utf-8 text encoding is supported")


class WorkspaceStore:
    """Local registry for managed project workspaces."""

    def __init__(self, projects_root: Path | None = None) -> None:
        self.projects_root = (projects_root or managed_projects_root(create=True)).resolve()
        self.projects_root.mkdir(parents=True, exist_ok=True)

    @property
    def registry_path(self) -> Path:
        return self.projects_root / WORKSPACE_REGISTRY_FILE

    def list(self) -> list[ManagedWorkspace]:
        registry = self._load_registry()
        workspaces: dict[str, ManagedWorkspace] = {}

        for item in registry.values():
            try:
                workspace = self._from_dict(item)
            except (TypeError, ValueError):
                continue
            if Path(workspace.root_path).exists():
                workspaces[workspace.id] = workspace

        for manifest_path in self.projects_root.glob(f"*/{WORKSPACE_MANIFEST_FILE}"):
            try:
                workspace = self._from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if Path(workspace.root_path).exists():
                workspaces.setdefault(workspace.id, workspace)

        return sorted(workspaces.values(), key=lambda item: item.updated_at, reverse=True)

    def get(self, workspace_id: str) -> ManagedWorkspace:
        safe_id = safe_workspace_id(workspace_id)
        registry = self._load_registry()
        item = registry.get(safe_id)
        if item is not None:
            workspace = self._from_dict(item)
            if Path(workspace.root_path).exists():
                return workspace

        manifest_path = self.projects_root / safe_id / WORKSPACE_MANIFEST_FILE
        if manifest_path.is_file():
            workspace = self._from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
            if Path(workspace.root_path).exists():
                return workspace

        raise WorkspaceNotFoundError(safe_id)

    def import_zip(
        self,
        zip_path: str | Path,
        *,
        original_filename: str,
        name: str | None = None,
        description: str | None = None,
    ) -> ManagedWorkspace:
        archive_path = Path(zip_path).resolve()
        if not archive_path.is_file():
            raise WorkspaceImportError("uploaded zip file is missing")
        if archive_path.stat().st_size > MAX_ZIP_BYTES:
            raise WorkspaceImportError("uploaded zip file is too large")
        if not zipfile.is_zipfile(archive_path):
            raise WorkspaceImportError("uploaded file is not a valid zip archive")

        display_name = (name or Path(original_filename).stem or "Imported Workspace").strip()
        fallback_id = safe_workspace_id(Path(original_filename).stem, fallback="workspace")
        workspace_id = self._unique_id(display_name or original_filename, fallback=fallback_id)
        target_root = (self.projects_root / workspace_id).resolve()
        if not _is_relative_to(target_root, self.projects_root):
            raise WorkspaceImportError("workspace target escaped managed projects root")

        tmp_root = (self.projects_root / f".tmp-{workspace_id}-{uuid.uuid4().hex}").resolve()
        if not _is_relative_to(tmp_root, self.projects_root):
            raise WorkspaceImportError("temporary workspace target escaped managed projects root")

        try:
            file_count, total_size = self._extract_zip_safely(archive_path, tmp_root)
            shutil.move(str(tmp_root), str(target_root))

            now = _utc_now()
            workspace = ManagedWorkspace(
                id=workspace_id,
                name=display_name or workspace_id,
                kind="project",
                source="zip_upload",
                root_path=str(target_root),
                created_at=now,
                updated_at=now,
                metadata={
                    "description": (description or "").strip(),
                    "archive_filename": original_filename,
                    "file_count": file_count,
                    "total_size": total_size,
                },
            )
            self._register(workspace)
            return workspace
        except Exception:
            if tmp_root.exists():
                shutil.rmtree(tmp_root, ignore_errors=True)
            if target_root.exists() and not (target_root / WORKSPACE_MANIFEST_FILE).exists():
                shutil.rmtree(target_root, ignore_errors=True)
            raise

    def list_files(
        self,
        workspace_id: str,
        *,
        base_path: str = "",
        depth: int = 2,
        limit: int = 200,
    ) -> tuple[list[dict[str, Any]], bool]:
        workspace = self.get(workspace_id)
        root = Path(workspace.root_path).resolve()
        if base_path:
            base = self._resolve_relative_path(root, base_path)
        else:
            base = root
        if not base.exists():
            raise WorkspaceFileError("path not found")
        if base.is_file():
            return [self._file_entry(base, root, "file")], False
        if not base.is_dir():
            raise WorkspaceFileError("path is not a directory")

        max_depth = max(0, min(depth, 20))
        max_items = max(1, min(limit, 2000))
        items: list[dict[str, Any]] = []

        for current_root, dirs, files in os.walk(base):
            current = Path(current_root)
            rel_dir = current.relative_to(base)
            current_depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
            dirs.sort()
            files.sort()
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            if current_depth >= max_depth:
                dirs[:] = []

            for dirname in dirs:
                entry = current / dirname
                items.append(self._file_entry(entry, root, "directory"))
                if len(items) >= max_items:
                    return items, True

            for filename in files:
                if filename == WORKSPACE_MANIFEST_FILE or filename.startswith("."):
                    continue
                entry = current / filename
                items.append(self._file_entry(entry, root, "file"))
                if len(items) >= max_items:
                    return items, True

        return items, False

    def read_text_file(
        self,
        workspace_id: str,
        relative_path: str,
        *,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        encoding = _normalize_text_encoding(encoding)
        workspace = self.get(workspace_id)
        root = Path(workspace.root_path).resolve()
        path = self._resolve_relative_path(root, relative_path)
        if not path.exists():
            raise WorkspaceFileError("file not found")
        if not path.is_file():
            raise WorkspaceFileError("path is not a file")

        size = path.stat().st_size
        if size > MAX_TEXT_FILE_BYTES:
            raise WorkspaceFileError("file is too large to edit as text")

        data = path.read_bytes()
        if b"\x00" in data:
            raise WorkspaceFileError("file appears to be binary")
        try:
            content = data.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise WorkspaceFileError(f"file is not valid {encoding} text") from exc

        return {
            **self._file_entry(path, root, "file"),
            "content": content,
            "encoding": encoding,
            "editable": True,
        }

    def write_text_file(
        self,
        workspace_id: str,
        relative_path: str,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        encoding = _normalize_text_encoding(encoding)
        workspace = self.get(workspace_id)
        root = Path(workspace.root_path).resolve()
        path = self._resolve_relative_path(root, relative_path)
        try:
            encoded = content.encode(encoding)
        except (LookupError, UnicodeEncodeError) as exc:
            raise WorkspaceFileError(f"content is not valid {encoding} text") from exc
        if len(encoded) > MAX_TEXT_FILE_BYTES:
            raise WorkspaceFileError("content is too large to save as a workspace text file")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)

        workspace.updated_at = _utc_now()
        workspace.metadata = dict(workspace.metadata or {})
        workspace.metadata["last_file_edit_at"] = workspace.updated_at
        self._register(workspace)

        return {
            **self._file_entry(path, root, "file"),
            "content": content,
            "encoding": encoding,
            "editable": True,
        }

    def _file_entry(self, path: Path, root: Path, kind: str) -> dict[str, Any]:
        stat_result = path.stat()
        return {
            "path": path.relative_to(root).as_posix(),
            "kind": kind,
            "size": stat_result.st_size if kind == "file" else None,
            "modified_at": datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat(),
        }

    def _resolve_relative_path(self, root: Path, raw_path: str | os.PathLike[str]) -> Path:
        relative_path = _safe_workspace_relative_path(raw_path)
        resolved = (root / relative_path).resolve()
        if not _is_relative_to(resolved, root):
            raise WorkspaceFileError("path escapes workspace root")
        return resolved

    def _extract_zip_safely(self, archive_path: Path, destination: Path) -> tuple[int, int]:
        destination.mkdir(parents=True, exist_ok=False)
        root = destination.resolve()
        file_count = 0
        total_size = 0

        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_FILE_COUNT:
                raise WorkspaceImportError("zip contains too many entries")

            planned: list[tuple[zipfile.ZipInfo, Path]] = []
            for info in infos:
                relative_path = _validate_zip_info(info)
                if not info.is_dir():
                    file_count += 1
                    total_size += info.file_size
                if total_size > MAX_ZIP_TOTAL_BYTES:
                    raise WorkspaceImportError("zip uncompressed size is too large")
                planned.append((info, relative_path))

            for info, relative_path in planned:
                target_path = (root / relative_path).resolve()
                if not _is_relative_to(target_path, root):
                    raise WorkspaceImportError(f"zip path escapes workspace root: {info.filename}")
                if info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)
                copied = 0
                with archive.open(info) as source, target_path.open("wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > MAX_ZIP_FILE_BYTES:
                            raise WorkspaceImportError(
                                f"zip member expanded beyond limit: {info.filename}"
                            )
                        target.write(chunk)

        return file_count, total_size

    def _unique_id(self, value: str, *, fallback: str) -> str:
        base_id = safe_workspace_id(value, fallback=fallback)
        existing = set(self._load_registry())
        existing.update(path.name for path in self.projects_root.iterdir() if path.is_dir())
        if base_id not in existing:
            return base_id

        for index in range(2, 10000):
            candidate = f"{base_id}-{index}"
            if candidate not in existing:
                return candidate
        raise WorkspaceImportError("unable to allocate a unique workspace id")

    def _register(self, workspace: ManagedWorkspace) -> None:
        data = workspace.to_dict()
        manifest_path = Path(workspace.root_path) / WORKSPACE_MANIFEST_FILE
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        registry = self._load_registry()
        registry[workspace.id] = data
        self._write_registry(registry)

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        if not self.registry_path.is_file():
            return {}
        try:
            loaded = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(loaded, dict):
            return {}
        return {str(key): value for key, value in loaded.items() if isinstance(value, dict)}

    def _write_registry(self, data: dict[str, dict[str, Any]]) -> None:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.projects_root,
            delete=False,
            suffix=".tmp",
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            temp_path = Path(file.name)
        temp_path.replace(self.registry_path)

    def _from_dict(self, data: dict[str, Any]) -> ManagedWorkspace:
        required = {
            "id",
            "name",
            "kind",
            "source",
            "root_path",
            "created_at",
            "updated_at",
            "metadata",
        }
        missing = required.difference(data)
        if missing:
            raise ValueError(f"workspace manifest missing fields: {sorted(missing)}")
        workspace = ManagedWorkspace(
            id=str(data["id"]),
            name=str(data["name"]),
            kind=str(data["kind"]),
            source=str(data["source"]),
            root_path=str(data["root_path"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            metadata=dict(data.get("metadata") or {}),
        )
        root_path = Path(workspace.root_path).resolve()
        if not _is_relative_to(root_path, self.projects_root):
            raise ValueError("workspace root is outside managed projects root")
        workspace.root_path = str(root_path)
        return workspace
