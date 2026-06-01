"""Edit file capability for precise string replacement inside the workspace."""

from __future__ import annotations

from typing import Any, List

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

from ._safety import resolve_workspace_path


_DEFAULT_DESCRIPTION = (
    "受限工作区文件精确替换工具：将文件中匹配的 old_string 替换为 new_string。"
    "什么时候用：改大文件（>8KB）的某行或某段，避免读全文重写；你已经知道要替换的精确文本（含缩进/换行）。"
    "什么时候不用：创建新文件或全文重写时使用 write_file。"
    "默认 old_string 必须在文件中只出现一次；要批量替换时显式传 replace_all=True。"
    "old_string 等于 new_string、文件不存在或路径越权都会直接报错且不会改写文件。"
)


class EditFileCapability(CapabilityBase):
    """Replace a unique substring inside an existing workspace file."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return get_tool_description(self.name, _DEFAULT_DESCRIPTION)

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
                    "old_string": {
                        "type": "string",
                        "description": (
                            "要被替换的精确文本，必须完全匹配（含缩进/换行）。"
                            "默认必须在文件中只出现一次，否则需要 replace_all=True。"
                        ),
                    },
                    "new_string": {
                        "type": "string",
                        "description": "替换后的文本；不能等于 old_string。",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "是否替换所有匹配，默认 False。",
                        "default": False,
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认 utf-8",
                        "default": "utf-8",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            returns="替换结果元数据或错误说明",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Any:
        file_path = kwargs.get("file_path", "")
        old_string = kwargs.get("old_string", "")
        new_string = kwargs.get("new_string", "")
        replace_all = bool(kwargs.get("replace_all", False))
        encoding = kwargs.get("encoding", "utf-8")

        if not file_path:
            return {"error": "file_path is required"}
        if old_string == "":
            return {"error": "old_string is required and cannot be empty"}
        if old_string == new_string:
            return {
                "error": "new_string must differ from old_string",
            }

        try:
            resolved_path = resolve_workspace_path(file_path)
        except (PermissionError, ValueError) as exc:
            return {"error": str(exc)}

        try:
            content = resolved_path.read_text(encoding=encoding)
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to read file: {exc}"}

        match_lines = _find_match_lines(content, old_string)
        match_count = content.count(old_string)

        if match_count == 0:
            return {
                "error": (
                    f"old_string not found in {file_path}; check exact whitespace and indentation"
                ),
                "suggestions": [
                    "use file_search or read_file to confirm the exact text before retrying",
                ],
            }

        if match_count > 1 and not replace_all:
            return {
                "error": (
                    f"old_string occurs {match_count} times in {file_path}; "
                    "add more surrounding context to make it unique or pass replace_all=True"
                ),
                "suggestions": [
                    f"match at line {ln}" for ln in match_lines
                ],
            }

        try:
            new_content = content.replace(old_string, new_string)
            resolved_path.write_text(new_content, encoding=encoding)
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to write file: {exc}"}

        return {
            "success": True,
            "file_path": str(resolved_path),
            "replacements": match_count,
        }


def _find_match_lines(content: str, needle: str) -> List[int]:
    """Return 1-based line numbers where ``needle`` begins in ``content``."""

    if not needle:
        return []
    lines: List[int] = []
    cursor = 0
    while True:
        idx = content.find(needle, cursor)
        if idx == -1:
            break
        # 1-based line number for the start of the match
        line_no = content.count("\n", 0, idx) + 1
        lines.append(line_no)
        cursor = idx + max(1, len(needle))
    return lines
