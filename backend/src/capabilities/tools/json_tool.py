"""JSON validation and formatting capability."""

from __future__ import annotations

import json
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema


class JsonToolCapability(CapabilityBase):
    """Validate, format, minify, and query JSON values."""

    @property
    def name(self) -> str:
        return "json_tool"

    @property
    def description(self) -> str:
        return "JSON 工具：校验、格式化、压缩，并支持简单路径查询"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "JSON 文本",
                    },
                    "operation": {
                        "type": "string",
                        "description": "操作: validate | pretty | minify | query",
                        "default": "validate",
                    },
                    "path": {
                        "type": "string",
                        "description": "query 操作用的点路径，例如 users.0.name",
                    },
                },
                "required": ["text"],
            },
            returns="JSON 操作结果",
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        text = str(kwargs.get("text", ""))
        operation = str(kwargs.get("operation") or "validate")
        path = str(kwargs.get("path") or "")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return {
                "valid": False,
                "error": exc.msg,
                "line": exc.lineno,
                "column": exc.colno,
            }

        if operation == "pretty":
            return {
                "valid": True,
                "text": json.dumps(data, ensure_ascii=False, indent=2),
                "type": type(data).__name__,
            }
        if operation == "minify":
            return {
                "valid": True,
                "text": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                "type": type(data).__name__,
            }
        if operation == "query":
            if not path:
                return {"valid": True, "error": "path is required for query"}
            try:
                return {"valid": True, "path": path, "value": self._query(data, path)}
            except Exception as exc:
                return {"valid": True, "error": f"path not found: {str(exc)}"}

        return {"valid": True, "type": type(data).__name__}

    @staticmethod
    def _query(data: Any, path: str) -> Any:
        current = data
        for part in path.split("."):
            if isinstance(current, list):
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(part)
        return current
