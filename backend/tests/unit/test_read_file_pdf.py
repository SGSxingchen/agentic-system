"""PDF / binary handling tests for the ``read_file`` capability."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.read_file import ReadFileCapability


def _make_pdf() -> bytes:
    """Build a minimal valid 2-page text PDF (catalog + xref + EOF)."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R 5 0 R]/Count 2>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 6 0 R>>>>>>",
    ]
    s1 = b"BT /F1 12 Tf 20 100 Td (Hello PDF page1) Tj ET"
    objs.append(b"<</Length " + str(len(s1)).encode() + b">>stream\n" + s1 + b"\nendstream")
    objs.append(
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 7 0 R"
        b"/Resources<</Font<</F1 6 0 R>>>>>>"
    )
    objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    s2 = b"BT /F1 12 Tf 20 100 Td (Second page2 here) Tj ET"
    objs.append(b"<</Length " + str(len(s2)).encode() + b">>stream\n" + s2 + b"\nendstream")

    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(out)
    size = len(objs) + 1
    out += b"xref\n0 " + str(size).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<</Size " + str(size).encode() + b"/Root 1 0 R>>\n"
        b"startxref\n" + str(xref).encode() + b"\n%%EOF"
    )
    return out


class TestReadFilePdf:
    @pytest.mark.asyncio
    async def test_read_pdf_extracts_all_pages(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "doc.pdf").write_bytes(_make_pdf())

        result = await ReadFileCapability().execute(file_path="doc.pdf")

        assert "error" not in result
        assert result["file_type"] == "pdf"
        assert result["total_pages"] == 2
        assert result["returned_pages"] == 2
        assert "Hello PDF page1" in result["content"]
        assert "Second page2 here" in result["content"]
        assert "--- Page 1 ---" in result["content"]

    @pytest.mark.asyncio
    async def test_read_pdf_page_range(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "doc.pdf").write_bytes(_make_pdf())

        result = await ReadFileCapability().execute(file_path="doc.pdf", pages="2")

        assert result["returned_pages"] == 1
        assert "Second page2 here" in result["content"]
        assert "Hello PDF page1" not in result["content"]

    @pytest.mark.asyncio
    async def test_pdf_detected_by_magic_bytes_without_extension(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        # No .pdf suffix — detection must fall back to the %PDF magic bytes.
        (tmp_path / "report").write_bytes(_make_pdf())

        result = await ReadFileCapability().execute(file_path="report")

        assert result.get("file_type") == "pdf"
        assert result["total_pages"] == 2

    @pytest.mark.asyncio
    async def test_binary_non_pdf_returns_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe")

        result = await ReadFileCapability().execute(file_path="blob.bin")

        assert "error" in result
        assert "content" not in result

    @pytest.mark.asyncio
    async def test_invalid_pages_returns_helpful_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "doc.pdf").write_bytes(_make_pdf())

        result = await ReadFileCapability().execute(file_path="doc.pdf", pages="abc")

        assert "error" in result
        assert "pages" in result["error"]


class TestReadFileEncoding:
    @pytest.mark.asyncio
    async def test_gb18030_text_not_misreported_as_binary(self, tmp_path, monkeypatch):
        """中文 Windows 上的 GB18030 文本应被解码，而不是判成二进制。"""
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        body = "你好，世界\n第二行"
        (tmp_path / "gbk.txt").write_bytes(body.encode("gb18030"))

        result = await ReadFileCapability().execute(file_path="gbk.txt")

        assert "error" not in result
        assert "你好" in result["content"]
        assert result.get("encoding") == "gb18030"

    @pytest.mark.asyncio
    async def test_utf8_bom_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "bom.txt").write_bytes(b"\xef\xbb\xbfhello")

        result = await ReadFileCapability().execute(file_path="bom.txt")

        assert "error" not in result
        # utf-8-sig 解码会去掉 BOM
        assert result["content"] == "hello"

    @pytest.mark.asyncio
    async def test_directory_path_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "subdir").mkdir()

        result = await ReadFileCapability().execute(file_path="subdir")

        assert "error" in result
        assert "directory" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_large_text_default_read_is_bounded(self, tmp_path, monkeypatch):
        """超过整读字符上限时，默认读取应有界并给出续读提示。"""
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        body = "\n".join(f"line{i} " + "x" * 50 for i in range(1000))
        (tmp_path / "big.txt").write_text(body, encoding="utf-8")

        result = await ReadFileCapability().execute(file_path="big.txt")

        assert "error" not in result
        # 没有整读全部内容
        assert result["returned_lines"] < result["total_lines"]
        assert "note" in result
