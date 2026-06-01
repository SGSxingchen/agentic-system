"""Workspace safety helpers for file and shell tools."""

from __future__ import annotations

import os
from pathlib import Path

from core.workspace import project_root, resolve_project_path, resolve_workspace_root


def get_workspace_root() -> Path:
    """Return the allowed workspace root for tool access.

    优先级:
    1. ``core.task.context._workspace_root_cv`` 设置的 worktree 路径（Phase C 子 Agent 隔离）
    2. ``AGENTIC_WORKSPACE_ROOT`` 环境变量
    3. ``core.config.get_tool_runtime_config("file").workspace_root``
    4. 项目根目录下 ``./workspace``
    """

    try:
        from core.task.context import get_workspace_root_override

        override = get_workspace_root_override()
        if override is not None:
            root = Path(override).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            return root
    except Exception:
        pass

    configured = os.getenv("AGENTIC_WORKSPACE_ROOT", "").strip()
    if configured:
        return resolve_workspace_root(configured)

    try:
        from core.config import get_tool_runtime_config

        configured = get_tool_runtime_config("file").get("workspace_root", "")
        if configured:
            return resolve_workspace_root(str(configured))
    except Exception:
        pass

    return resolve_workspace_root()


def _boundary_enforced() -> bool:
    """工作区边界是否强制。默认 False（放行越界路径）。

    优先级：环境变量 ``AGENTIC_ENFORCE_WORKSPACE_BOUNDARY`` >
    ``get_tool_runtime_config("file").enforce_workspace_boundary`` > 默认 False。
    """

    env = os.getenv("AGENTIC_ENFORCE_WORKSPACE_BOUNDARY", "").strip().lower()
    if env:
        return env in {"1", "true", "yes", "on"}

    try:
        from core.config import get_tool_runtime_config

        return bool(
            get_tool_runtime_config("file").get("enforce_workspace_boundary", False)
        )
    except Exception:
        return False


def resolve_workspace_path(raw_path: str) -> Path:
    """Resolve a user path.

    相对路径始终落到工作区根目录下（保留聊天室工作区绑定/附件相对路径语义）。
    绝对路径与越界路径默认放行；仅当 ``_boundary_enforced()`` 为真时才强制沙箱、
    对越界路径抛 ``PermissionError``。
    """

    if not raw_path:
        raise ValueError("path is required")

    root = get_workspace_root()
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()

    if _boundary_enforced():
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


def get_project_root() -> Path:
    """Return repository root for operations that must run against git/config."""

    return project_root()


def resolve_project_relative_path(raw_path: str | os.PathLike[str], default: str) -> Path:
    """Resolve a user-configurable storage path relative to the project root."""

    return resolve_project_path(raw_path, default=default)


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
