"""Capability for sending generated artifacts, files and images to the frontend."""

from __future__ import annotations

import base64
import mimetypes
from typing import Any

from core.artifacts import ArtifactStore
from core.capability.base import CapabilityBase, CapabilitySchema

from ._safety import resolve_workspace_path


class FrontendArtifactCapability(CapabilityBase):
    """Create a frontend-visible artifact and return preview/download metadata."""

    @property
    def name(self) -> str:
        return "create_frontend_artifact"

    @property
    def description(self) -> str:
        return (
            "把文件或生成内容发送到前端 Artifact 区，供用户预览/打开/下载。"
            "推荐做法：要发送工作区里已存在的本地文件（含图片、二进制），只需传 path（工作区内路径），"
            "工具会自动读取并编码，无需手动 base64。"
            "也可不传 path，直接用 content 传入文本或 base64 内容。"
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内的本地文件路径；传了它就会自动读取该文件并编码，无需再传 content/content_encoding。",
                    },
                    "kind": {"type": "string", "enum": ["html", "markdown", "code", "image", "file", "text"]},
                    "title": {"type": "string", "description": "Artifact 展示标题"},
                    "content": {"type": "string", "description": "文本内容或 base64 文件内容（未传 path 时使用）"},
                    "mime_type": {"type": "string", "description": "MIME 类型，如 text/html、image/png"},
                    "filename": {"type": "string", "description": "下载文件名"},
                    "content_encoding": {"type": "string", "enum": ["text", "base64"], "default": "text"},
                    "session_id": {"type": "string", "description": "可选会话 ID，用于前端筛选"},
                    "message_id": {"type": "string", "description": "可选消息 ID"},
                    "metadata": {"type": "object", "description": "额外元数据"},
                },
                "required": ["title"],
            },
            returns="Artifact 元数据，包含 id、download_url、open_url、content_url，可由前端预览/下载/打开。",
            is_read_only=False,
            is_concurrency_safe=True,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Any:
        try:
            kind = str(kwargs.get("kind") or "").strip()
            content = str(kwargs.get("content") or "")
            content_encoding = str(kwargs.get("content_encoding") or "text")
            mime_type = str(kwargs.get("mime_type") or "")
            filename = str(kwargs.get("filename") or "")

            raw_path = str(kwargs.get("path") or "").strip()
            if raw_path:
                file_path = resolve_workspace_path(raw_path)
                if not file_path.exists() or not file_path.is_file():
                    return {"error": f"create_frontend_artifact failed: file not found: {raw_path}"}
                content = base64.b64encode(file_path.read_bytes()).decode("ascii")
                content_encoding = "base64"
                if not filename:
                    filename = file_path.name
                if not mime_type:
                    mime_type = mimetypes.guess_type(file_path.name)[0] or ""
                if not kind:
                    kind = "image" if mime_type.startswith("image/") else "file"
            elif not content:
                return {"error": "create_frontend_artifact failed: provide either 'path' or 'content'"}

            artifact = ArtifactStore().create_artifact(
                kind=kind or "file",
                title=str(kwargs.get("title") or "Artifact"),
                content=content,
                mime_type=mime_type,
                filename=filename,
                content_encoding=content_encoding,
                session_id=kwargs.get("session_id"),
                message_id=kwargs.get("message_id"),
                source="agent_tool",
                metadata=kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {},
            )
            return {"success": True, "artifact": artifact}
        except Exception as exc:
            return {"error": f"create_frontend_artifact failed: {exc}"}
