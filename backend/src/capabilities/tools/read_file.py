"""Read file capability with workspace boundary checks."""

from __future__ import annotations

from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

from ._safety import resolve_workspace_path


_MAX_LIMIT = 2000
_DEFAULT_LIMIT = 200


class ReadFileCapability(CapabilityBase):
    """读取工作区内的文件内容。"""

    @property
    def name(self) -> str:
        return "read_file"

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
                        "description": "要读取的文件路径（仅允许工作区内路径）",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认 utf-8",
                        "default": "utf-8",
                    },
                    "offset": {
                        "type": "integer",
                        "description": (
                            "起始行号 (0-based)。不传时读取整文件；传入时按行切片返回。"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"最多读取的行数，默认 {_DEFAULT_LIMIT}，最大 {_MAX_LIMIT}。"
                            "仅在传入 offset 或 limit 时启用分页模式。"
                        ),
                    },
                },
                "required": ["file_path"],
            },
            returns="文件内容字符串",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Any:
        file_path = kwargs.get("file_path", "")
        encoding = kwargs.get("encoding", "utf-8")
        raw_offset = kwargs.get("offset")
        raw_limit = kwargs.get("limit")

        if not file_path:
            return {"error": "file_path is required"}

        try:
            resolved_path = resolve_workspace_path(file_path)
            with open(resolved_path, "r", encoding=encoding) as file:
                content = file.read()
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to read file: {str(exc)}"}

        # Backward-compatible fast path: when neither offset nor limit is set,
        # return the full file just like before.
        if raw_offset is None and raw_limit is None:
            return {
                "content": content,
                "file_path": str(resolved_path),
                "size": len(content),
            }

        try:
            offset = int(raw_offset) if raw_offset is not None else 0
        except (TypeError, ValueError):
            return {"error": "offset must be an integer"}
        try:
            limit = int(raw_limit) if raw_limit is not None else _DEFAULT_LIMIT
        except (TypeError, ValueError):
            return {"error": "limit must be an integer"}

        if offset < 0:
            offset = 0
        if limit < 0:
            limit = 0
        if limit > _MAX_LIMIT:
            limit = _MAX_LIMIT

        # splitlines(keepends=True) preserves the original line terminators so
        # joining the slice yields a faithful slice of the original text.
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        sliced = lines[offset : offset + limit] if offset < total_lines else []
        sliced_content = "".join(sliced)

        return {
            "content": sliced_content,
            "file_path": str(resolved_path),
            "size": len(sliced_content),
            "offset": offset,
            "limit": limit,
            "total_lines": total_lines,
            "returned_lines": len(sliced),
        }
