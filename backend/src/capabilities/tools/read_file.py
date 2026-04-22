"""Read file capability with workspace boundary checks."""

from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema

from ._safety import resolve_workspace_path


class ReadFileCapability(CapabilityBase):
    """读取工作区内的文件内容。"""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取工作区内指定路径的文件内容"

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
