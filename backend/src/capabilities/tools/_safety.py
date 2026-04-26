"""Workspace safety helpers for file and shell tools."""

from __future__ import annotations

import os
from pathlib import Path


def get_workspace_root() -> Path:
    """Return the allowed workspace root for tool access."""

    configured = os.getenv("AGENTIC_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    try:
        from core.config import get_tool_runtime_config

        configured = get_tool_runtime_config("file").get("workspace_root", "")
        if configured:
            return Path(str(configured)).expanduser().resolve()
    except Exception:
        pass

    return Path(__file__).resolve().parents[4]


def resolve_workspace_path(raw_path: str) -> Path:
    """Resolve a user path and ensure it stays inside the workspace."""

    if not raw_path:
        raise ValueError("path is required")

    root = get_workspace_root()
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()

    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"path '{raw_path}' is outside the workspace root '{root}'"
        ) from exc

    return path


def resolve_workspace_cwd(raw_cwd: str | None) -> Path:
    """Resolve a shell working directory inside the workspace."""

    if raw_cwd:
        return resolve_workspace_path(raw_cwd)
    return get_workspace_root()


def ensure_shell_tool_enabled() -> None:
    """Require an explicit opt-in before enabling shell execution."""

    try:
        from core.config import get_tool_runtime_config

        enabled = bool(get_tool_runtime_config("shell").get("enabled", False))
    except Exception:
        enabled = False

    if not enabled:
        raise PermissionError(
            "shell tool is disabled by default; set ENABLE_SHELL_TOOL=true for trusted local development"
        )
