"""Capability for sending generated artifacts, files and images to the frontend."""

from __future__ import annotations

from typing import Any

from core.artifacts import ArtifactStore
from core.capability.base import CapabilityBase, CapabilitySchema


class FrontendArtifactCapability(CapabilityBase):
    """Create a frontend-visible artifact and return preview/download metadata."""

    @property
    def name(self) -> str:
        return "create_frontend_artifact"

    @property
    def description(self) -> str:
        return (
            "创建可在前端 Artifact 预览区展示的 HTML、Markdown、代码、图片或文件。"
            "适用于需要把生成结果作为可切换、可下载、可打开的前端附件呈现时。"
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["html", "markdown", "code", "image", "file", "text"]},
                    "title": {"type": "string", "description": "Artifact 展示标题"},
                    "content": {"type": "string", "description": "文本内容或 base64 文件内容"},
                    "mime_type": {"type": "string", "description": "MIME 类型，如 text/html、image/png"},
                    "filename": {"type": "string", "description": "下载文件名"},
                    "content_encoding": {"type": "string", "enum": ["text", "base64"], "default": "text"},
                    "session_id": {"type": "string", "description": "可选会话 ID，用于前端筛选"},
                    "message_id": {"type": "string", "description": "可选消息 ID"},
                    "metadata": {"type": "object", "description": "额外元数据"},
                },
                "required": ["kind", "title", "content"],
            },
            returns="Artifact 元数据，包含 id、download_url、open_url、content_url，可由前端预览/下载/打开。",
            is_read_only=False,
            is_concurrency_safe=True,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Any:
        try:
            artifact = ArtifactStore().create_artifact(
                kind=str(kwargs.get("kind") or "file"),
                title=str(kwargs.get("title") or "Artifact"),
                content=str(kwargs.get("content") or ""),
                mime_type=str(kwargs.get("mime_type") or ""),
                filename=str(kwargs.get("filename") or ""),
                content_encoding=str(kwargs.get("content_encoding") or "text"),
                session_id=kwargs.get("session_id"),
                message_id=kwargs.get("message_id"),
                source="agent_tool",
                metadata=kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {},
            )
            return {"success": True, "artifact": artifact}
        except Exception as exc:
            return {"error": f"create_frontend_artifact failed: {exc}"}
