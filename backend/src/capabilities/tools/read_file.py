"""Read file capability with workspace boundary checks."""

from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

from ._safety import resolve_workspace_path


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

        if not file_path:
            return {"error": "file_path is required"}

        try:
            resolved_path = resolve_workspace_path(file_path)
            with open(resolved_path, "r", encoding=encoding) as file:
                content = file.read()
            return {
                "content": content,
                "file_path": str(resolved_path),
                "size": len(content),
            }
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Failed to read file: {str(exc)}"}
