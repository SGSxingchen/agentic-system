"""Write file capability with workspace boundary checks."""

from __future__ import annotations

from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

from ._safety import resolve_workspace_path


class WriteFileCapability(CapabilityBase):
    """Write content to files inside the current workspace only."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "目标文件路径，必须位于工作区内",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入文件的完整内容",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认 utf-8",
                        "default": "utf-8",
                    },
                },
                "required": ["file_path", "content"],
            },
            returns="写入结果元数据",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Any:
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")
        encoding = kwargs.get("encoding", "utf-8")

        if not file_path:
            return {"error": "file_path is required"}

        try:
            resolved_path = resolve_workspace_path(file_path)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(content, encoding=encoding)
            return {
                "success": True,
                "file_path": str(resolved_path),
                "bytes_written": len(content.encode(encoding)),
            }
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Failed to write file: {str(exc)}"}
