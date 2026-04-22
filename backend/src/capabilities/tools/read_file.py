"""ReadFile 能力插件 — 读取文件内容"""
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema


class ReadFileCapability(CapabilityBase):
    """读取指定路径的文件内容"""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取指定路径的文件内容，返回文件文本"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要读取的文件路径",
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
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            return {"content": content, "file_path": file_path, "size": len(content)}
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}
