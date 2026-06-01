"""Robustness fixes for assorted capability tools.

覆盖一次性改进：
- file_search 单文件出错只跳过、不整体失败
- frontend_artifact 超大文件提前拒绝
- json_tool query 语义清晰化（found 标记 + 非数字索引提示）
- write_file 非法编码名提前报错
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.file_search import FileSearchCapability
from capabilities.tools.frontend_artifact import FrontendArtifactCapability
from capabilities.tools.json_tool import JsonToolCapability
from capabilities.tools.write_file import WriteFileCapability


class TestFileSearchRobustness:
    @pytest.mark.asyncio
    async def test_broken_symlink_does_not_abort_search(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "real.py").write_text("print('hi')\n", encoding="utf-8")
        # 指向不存在目标的软链：stat() 会抛 FileNotFoundError。
        broken = tmp_path / "broken.py"
        try:
            broken.symlink_to(tmp_path / "does_not_exist.py")
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported on this platform/permission")

        result = await FileSearchCapability().execute(glob="*.py")

        assert "error" not in result
        names = {r["path"] for r in result["results"]}
        assert "real.py" in names  # 正常文件仍被搜到，没被坏软链带崩


class TestFrontendArtifactSize:
    @pytest.mark.asyncio
    async def test_oversized_file_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        from capabilities.tools import frontend_artifact

        monkeypatch.setattr(frontend_artifact, "_MAX_ARTIFACT_BYTES", 16)
        (tmp_path / "big.bin").write_bytes(b"x" * 64)

        result = await FrontendArtifactCapability().execute(path="big.bin", title="t")

        assert "error" in result
        assert "too large" in result["error"]


class TestJsonToolQuery:
    @pytest.mark.asyncio
    async def test_query_hit_sets_found_true(self):
        result = await JsonToolCapability().execute(
            text='{"users": [{"name": "Alice"}]}', operation="query", path="users.0.name"
        )
        assert result["found"] is True
        assert result["value"] == "Alice"

    @pytest.mark.asyncio
    async def test_query_non_numeric_list_index_clear_error(self):
        result = await JsonToolCapability().execute(
            text='[1, 2, 3]', operation="query", path="abc"
        )
        assert result["found"] is False
        assert "invalid list index" in result["error"]

    @pytest.mark.asyncio
    async def test_query_missing_key_found_false(self):
        result = await JsonToolCapability().execute(
            text='{"a": 1}', operation="query", path="b"
        )
        assert result["found"] is False
        assert "path not found" in result["error"]


class TestWriteFileEncoding:
    @pytest.mark.asyncio
    async def test_invalid_encoding_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        result = await WriteFileCapability().execute(
            file_path="x.txt", content="hi", encoding="utf16-le"  # 真实名是 utf-16-le
        )
        assert "error" in result
        assert "unknown encoding" in result["error"]
        assert not (tmp_path / "x.txt").exists()  # 校验失败不应留下文件
