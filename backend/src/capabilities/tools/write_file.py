"""WriteFile 能力插件 — 写入文件内容"""
import os
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema


class WriteFileCapability(CapabilityBase):
    """写入内容到指定路径的文件"""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "将内容写入指定路径的文件，自动创建目录"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要写入的文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的文件内容",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认 utf-8",
                        "default": "utf-8",
                    },
                },
                "required": ["file_path", "content"],
            },
            returns="写入结果",
        )

    async def execute(self, **kwargs: Any) -> Any:
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")
        encoding = kwargs.get("encoding", "utf-8")

        if not file_path:
            return {"error": "file_path is required"}

        try:
            # 自动创建目录
            dir_path = os.path.dirname(file_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(file_path, "w", encoding=encoding) as f:
                f.write(content)

            return {
                "success": True,
                "file_path": file_path,
                "bytes_written": len(content.encode(encoding)),
            }
        except Exception as e:
            return {"error": f"Failed to write file: {str(e)}"}
