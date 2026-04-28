"""Workspace file search capability."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema

from ._safety import get_workspace_root, resolve_workspace_path


class FileSearchCapability(CapabilityBase):
    """Search files by name and optional text query inside the workspace."""

    _SKIP_DIRS = {
        ".git",
        ".pytest_cache",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
    }

    @property
    def name(self) -> str:
        return "file_search"

    @property
    def description(self) -> str:
        return "在工作区内按文件名或文本内容搜索文件，自动跳过依赖和缓存目录"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "文件内容搜索关键词，可为空",
                    },
                    "glob": {
                        "type": "string",
                        "description": "文件名匹配模式，例如 *.py、*.tsx，默认 *",
                        "default": "*",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索起点，必须在工作区内，默认工作区根目录",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大结果数，默认 20",
                        "default": 20,
                    },
                    "include_snippets": {
                        "type": "boolean",
                        "description": "是否返回命中行片段，默认 true",
                        "default": True,
                    },
                },
            },
            returns="匹配文件列表和可选命中片段",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or "")
        glob_pattern = str(kwargs.get("glob") or "*")
        raw_path = kwargs.get("path")
        max_results = int(kwargs.get("max_results", 20) or 20)
        include_snippets = bool(kwargs.get("include_snippets", True))

        try:
            root = resolve_workspace_path(raw_path) if raw_path else get_workspace_root()
        except Exception as exc:
            return {"error": str(exc)}

        if not root.exists():
            return {"error": f"path does not exist: {root}"}

        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        max_results = max(1, min(max_results, 100))

        for file_path in self._iter_files(root):
            if not fnmatch.fnmatch(file_path.name, glob_pattern):
                continue

            match_reason = "name" if query_lower and query_lower in file_path.name.lower() else ""
            snippets: list[dict[str, Any]] = []

            if query and not match_reason:
                snippets = self._search_file_content(file_path, query_lower, include_snippets)
                if snippets:
                    match_reason = "content"
            elif query and include_snippets:
                snippets = self._search_file_content(file_path, query_lower, include_snippets)

            if query and not match_reason:
                continue

            results.append(
                {
                    "path": file_path.relative_to(get_workspace_root()).as_posix(),
                    "size": file_path.stat().st_size,
                    "match": match_reason or "glob",
                    "snippets": snippets[:3],
                }
            )
            if len(results) >= max_results:
                break

        return {
            "query": query,
            "glob": glob_pattern,
            "root": str(root),
            "count": len(results),
            "results": results,
        }

    def _iter_files(self, root: Path):
        if root.is_file():
            yield root
            return

        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                dirname for dirname in dirnames if dirname not in self._SKIP_DIRS
            ]
            for filename in filenames:
                yield Path(current_root) / filename

    @staticmethod
    def _search_file_content(
        file_path: Path,
        query_lower: str,
        include_snippets: bool,
    ) -> list[dict[str, Any]]:
        if file_path.stat().st_size > 1_000_000:
            return []

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        snippets = []
        for line_no, line in enumerate(text.splitlines(), 1):
            if query_lower in line.lower():
                if include_snippets:
                    snippets.append({"line": line_no, "text": line.strip()[:240]})
                else:
                    snippets.append({"line": line_no})
                if len(snippets) >= 3:
                    break
        return snippets
