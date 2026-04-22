"""Workspace safety helpers for file and shell tools."""

from __future__ import annotations

import os
from pathlib import Path


def get_workspace_root() -> Path:
    """Return the allowed workspace root for tool access."""

    configured = os.getenv("AGENTIC_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

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

    value = os.getenv("ENABLE_SHELL_TOOL", "").strip().lower()
    if value not in {"1", "true", "yes", "on"}:
        raise PermissionError(
            "shell tool is disabled by default; set ENABLE_SHELL_TOOL=true for trusted local development"
        )
