"""Tests for the ``edit_file`` capability."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.edit_file import EditFileCapability


class TestEditFileCapability:
    @pytest.mark.asyncio
    async def test_edit_file_unique_match_replaces(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "note.txt"
        target.write_text("hello world\nsecond line\n", encoding="utf-8")

        tool = EditFileCapability()
        result = await tool.execute(
            file_path="note.txt",
            old_string="hello world",
            new_string="hello agent",
        )

        assert result.get("success") is True
        assert result["replacements"] == 1
        assert target.read_text(encoding="utf-8") == "hello agent\nsecond line\n"

    @pytest.mark.asyncio
    async def test_edit_file_multiple_matches_errors_unless_replace_all(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "dup.txt"
        target.write_text("foo\nbar\nfoo\nbaz\nfoo\n", encoding="utf-8")

        tool = EditFileCapability()
        result = await tool.execute(
            file_path="dup.txt",
            old_string="foo",
            new_string="qux",
        )

        assert "error" in result
        # surface the line numbers (1-based) of all matches so the agent can
        # pick more context to disambiguate
        assert "suggestions" in result
        assert any("1" in s for s in result["suggestions"])
        assert any("3" in s for s in result["suggestions"])
        assert any("5" in s for s in result["suggestions"])
        # file must remain unchanged on multi-match error
        assert target.read_text(encoding="utf-8") == "foo\nbar\nfoo\nbaz\nfoo\n"

    @pytest.mark.asyncio
    async def test_edit_file_replace_all_works(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "dup.txt"
        target.write_text("foo\nbar\nfoo\nbaz\nfoo\n", encoding="utf-8")

        tool = EditFileCapability()
        result = await tool.execute(
            file_path="dup.txt",
            old_string="foo",
            new_string="qux",
            replace_all=True,
        )

        assert result.get("success") is True
        assert result["replacements"] == 3
        assert target.read_text(encoding="utf-8") == "qux\nbar\nqux\nbaz\nqux\n"

    @pytest.mark.asyncio
    async def test_edit_file_outside_workspace_blocked(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(workspace))

        tool = EditFileCapability()
        result = await tool.execute(
            file_path=str(outside),
            old_string="secret",
            new_string="leak",
        )

        assert "error" in result
        # outside path must not be touched
        assert outside.read_text(encoding="utf-8") == "secret"

    @pytest.mark.asyncio
    async def test_edit_file_old_equals_new_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        target = tmp_path / "note.txt"
        target.write_text("hello", encoding="utf-8")

        tool = EditFileCapability()
        result = await tool.execute(
            file_path="note.txt",
            old_string="hello",
            new_string="hello",
        )

        assert "error" in result
        assert target.read_text(encoding="utf-8") == "hello"

    @pytest.mark.asyncio
    async def test_edit_file_file_not_found_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))

        tool = EditFileCapability()
        result = await tool.execute(
            file_path="missing.txt",
            old_string="a",
            new_string="b",
        )

        assert "error" in result
