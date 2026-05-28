"""Pagination tests for the ``read_file`` capability."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.read_file import ReadFileCapability


class TestReadFilePagination:
    @pytest.mark.asyncio
    async def test_read_file_offset_limit_returns_slice(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "lines.txt"
        target.write_text(
            "\n".join(f"line{i}" for i in range(10)) + "\n",
            encoding="utf-8",
        )

        tool = ReadFileCapability()
        result = await tool.execute(file_path="lines.txt", offset=2, limit=3)

        assert "error" not in result
        # 0-based offset: line2/line3/line4
        assert result["content"] == "line2\nline3\nline4\n"
        assert result["offset"] == 2
        assert result["limit"] == 3
        assert result["total_lines"] == 10
        assert result["returned_lines"] == 3

    @pytest.mark.asyncio
    async def test_read_file_offset_beyond_eof_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "small.txt"
        target.write_text("a\nb\nc\n", encoding="utf-8")

        tool = ReadFileCapability()
        result = await tool.execute(file_path="small.txt", offset=999, limit=10)

        assert "error" not in result
        assert result["content"] == ""
        assert result["returned_lines"] == 0
        assert result["total_lines"] == 3

    @pytest.mark.asyncio
    async def test_read_file_default_no_pagination_unchanged(self, tmp_path, monkeypatch):
        """Without offset/limit kwargs the original full-content behavior is preserved."""
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "all.txt"
        body = "alpha\nbeta\ngamma\n"
        target.write_text(body, encoding="utf-8")

        tool = ReadFileCapability()
        result = await tool.execute(file_path="all.txt")

        assert "error" not in result
        assert result["content"] == body
        assert result["size"] == len(body)
        # When pagination is not requested we should not surface offset/limit/total_lines
        # (or they should mirror the full read).  Either way, content must match the file.
        assert "offset" not in result or result["offset"] == 0

    @pytest.mark.asyncio
    async def test_read_file_limit_capped_at_max(self, tmp_path, monkeypatch):
        """limit greater than 2000 is clamped to 2000."""
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "many.txt"
        body = "\n".join(f"l{i}" for i in range(2500)) + "\n"
        target.write_text(body, encoding="utf-8")

        tool = ReadFileCapability()
        result = await tool.execute(file_path="many.txt", offset=0, limit=10_000)

        assert "error" not in result
        assert result["limit"] == 2000
        assert result["returned_lines"] == 2000
