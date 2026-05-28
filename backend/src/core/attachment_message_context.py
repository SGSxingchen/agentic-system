"""Build a system reminder block from attachment IDs (Plan 3 P3 Task 25).

Bridges the AttachmentStore + workspace materialization layer (Task 24) with
the prompt assembly layer used by Agent invocation paths.

The block follows the A16 pattern used elsewhere in the codebase: an XML-like
tag containing per-file metadata + the *workspace path*, so the Agent can ask
the ``read_file`` tool to load the file content on demand.

Image attachments are intentionally **excluded** here — they go through the
LLM client's vision payload (Task 26). We only handle text / PDF / archive
types here, where the Agent reads bytes via ``read_file``.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Iterable, Optional

from .attachment import Attachment, AttachmentStore
from .attachment_workspace import link_attachment_to_workspace


__all__ = [
    "build_attachment_reminder",
    "build_attachment_image_blocks",
    "non_image_attachments",
    "image_attachments",
    "get_default_attachment_store",
]


logger = logging.getLogger(__name__)


# B1 Plan 3 P3 Task 26 — guard against shipping huge images inline. Anthropic
# accepts up to 5MB per image and OpenAI up to ~20MB; we cap conservatively
# at 4MB so we leave room for other context.
_MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def non_image_attachments(
    attachments: Iterable[Attachment],
) -> list[Attachment]:
    """Filter out ``image/*`` types — those go through vision payload."""

    return [
        att for att in attachments if not (att.mime_type or "").lower().startswith("image/")
    ]


def image_attachments(
    attachments: Iterable[Attachment],
) -> list[Attachment]:
    """Keep only ``image/*`` MIME types."""

    return [
        att for att in attachments if (att.mime_type or "").lower().startswith("image/")
    ]


def build_attachment_image_blocks(
    *,
    attachment_ids: Iterable[str],
    store: AttachmentStore,
    max_bytes: int = _MAX_INLINE_IMAGE_BYTES,
) -> list[dict]:
    """Materialize image attachments into neutral inline image blocks.

    Returns a list of dicts shaped like
    ``{"mime_type": ..., "data": <base64>, "name": ...}``  — Agent._build_messages
    appends them as multipart user content; LLM clients translate them into
    OpenAI ``image_url`` / Anthropic ``image`` source.

    Files larger than ``max_bytes`` or that cannot be read are skipped (logged
    at WARNING). The function is forgiving: a missing record just drops out.
    """

    ids = [str(i) for i in attachment_ids if i]
    if not ids:
        return []

    out: list[dict] = []
    for att_id in ids:
        att = store.get(att_id)
        if att is None:
            continue
        mime = (att.mime_type or "").lower()
        if not mime.startswith("image/"):
            continue
        if att.size_bytes and att.size_bytes > max_bytes:
            logger.warning(
                "skip image attachment %s: size %s > cap %s",
                att.id,
                att.size_bytes,
                max_bytes,
            )
            continue
        try:
            raw = Path(att.storage_path).read_bytes()
        except OSError as exc:
            logger.warning("read image attachment %s failed: %s", att.id, exc)
            continue
        if len(raw) > max_bytes:
            logger.warning(
                "skip image attachment %s: read %s bytes > cap %s",
                att.id,
                len(raw),
                max_bytes,
            )
            continue
        out.append(
            {
                "mime_type": att.mime_type,
                "data": base64.b64encode(raw).decode("ascii"),
                "name": att.filename or att.id,
            }
        )
    return out


def build_attachment_reminder(
    *,
    attachment_ids: Iterable[str],
    workspace_root: Path | str,
    store: AttachmentStore,
) -> str:
    """Materialize attachments into the workspace and return a system block.

    Returns an empty string when there are no consumable attachments — callers
    can append the result unconditionally.

    Side effect: each non-image attachment is linked / copied under
    ``<workspace_root>/.attachments/<id>/<filename>`` (Task 24).
    """

    ids = [str(i) for i in attachment_ids if i]
    if not ids:
        return ""

    resolved: list[tuple[Attachment, Path]] = []
    for att_id in ids:
        att = store.get(att_id)
        if att is None:
            continue
        if (att.mime_type or "").lower().startswith("image/"):
            continue  # vision path
        try:
            target = link_attachment_to_workspace(att, workspace_root)
        except Exception:
            # Linking failure should not break the chat turn; skip the file.
            continue
        resolved.append((att, target))

    if not resolved:
        return ""

    workspace_root_path = Path(workspace_root)
    lines: list[str] = ["<attached_files>"]
    for att, target in resolved:
        try:
            rel = target.resolve().relative_to(workspace_root_path.resolve())
            rel_str = str(rel).replace("\\", "/")
        except (OSError, ValueError):
            rel_str = str(target).replace("\\", "/")
        lines.append(
            '  <file id="{id}" path="{path}" mime="{mime}" size="{size}">{name}</file>'.format(
                id=_xml_escape(att.id),
                path=_xml_escape(rel_str),
                mime=_xml_escape(att.mime_type or "application/octet-stream"),
                size=int(att.size_bytes or 0),
                name=_xml_escape(att.filename or att.id),
            )
        )
    lines.append("</attached_files>")
    lines.append(
        "<reminder>用户在最近一条消息里附带了上述文件，需要时使用 read_file 工具按 path 读取。"
        "图片类附件请等待 vision 通道。</reminder>"
    )
    return "\n".join(lines)


def get_default_attachment_store() -> Optional[AttachmentStore]:
    """Helper to fetch the routes-layer singleton without circular imports."""

    try:
        from api.routes.attachments import _get_store  # type: ignore

        return _get_store()
    except Exception:
        return None
