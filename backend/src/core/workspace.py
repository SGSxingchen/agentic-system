"""Project workspace path helpers.

The runtime has two distinct roots:

- project root: repository/config/documentation location;
- workspace root: default mutable working directory for agent tools and
  generated runtime artifacts.

All relative workspace-style configuration is resolved against the project
root, never the current process cwd.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_WORKSPACE_DIR = "workspace"


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
