"""JSON validation and formatting capability."""

from __future__ import annotations

import json
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description


class JsonToolCapability(CapabilityBase):
    """Validate, format, minify, and query JSON values."""

    @property
    def name(self) -> str:
        return "json_tool"

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
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
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
                return {"valid": True, "found": False, "error": "path is required for query"}
            try:
                value = self._query(data, path)
            except ValueError as exc:
                # 对列表用了非数字索引（如 users.abc）。
                return {"valid": True, "found": False, "error": f"invalid list index in path: {exc}"}
            except (KeyError, IndexError) as exc:
                return {"valid": True, "found": False, "error": f"path not found: {exc}"}
            return {"valid": True, "found": True, "path": path, "value": value}

        return {"valid": True, "type": type(data).__name__}

    @staticmethod
    def _query(data: Any, path: str) -> Any:
        current = data
        for part in path.split("."):
            if isinstance(current, list):
                # int(part) 对非数字抛 ValueError，由 execute 转成清晰提示。
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(part)
        return current
