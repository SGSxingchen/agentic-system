"""Workspace ↔ attachment bridge (Plan 3 Phase P3 Task 24).

Lets Agents see uploaded attachments inside their sandboxed workspace by
materializing each attachment under ``<workspace_root>/.attachments/<id>/<name>``.

Strategy:
    1. Try ``Path.symlink_to`` (zero-copy on Linux/macOS).
    2. On ``OSError`` (Windows / restricted FS / dangling target) or
       ``NotImplementedError`` (older runtimes), fall back to ``shutil.copy2``.

The function is **idempotent** — if the target already exists it is returned
unchanged. Callers don't need to track per-task setup state.

This is the only safe path for ``read_file`` to access uploads, because the
``_safety`` layer rejects any path outside the workspace root.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .attachment import Attachment


__all__ = ["link_attachment_to_workspace"]


def link_attachment_to_workspace(att: Attachment, workspace_root: Path | str) -> Path:
    """Materialize ``att`` under ``workspace_root/.attachments/<id>/<filename>``.

    Returns the absolute target path inside the workspace root. The file at
    that path can be read with ``read_file`` because it is under the sandbox.
    """

    root = Path(workspace_root)
    target_dir = root / ".attachments" / att.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / att.filename

    if target.exists() or target.is_symlink():
        # Already linked / copied earlier (idempotent).
        return target

    src = Path(att.storage_path).resolve()
    try:
        target.symlink_to(src)
    except (OSError, NotImplementedError):
        # R6 — Windows / restricted FS without symlink privilege.
        # Fall back to a real copy so the Agent can still read the file.
        # Clean up half-created symlink if any (symlink_to may leave nothing
        # behind on most failures, but be defensive).
        try:
            if target.is_symlink() or target.exists():
                target.unlink()
        except OSError:
            pass
        shutil.copy2(src, target)
    return target
