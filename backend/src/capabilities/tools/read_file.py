"""Read file capability with workspace boundary checks.

像 Claude Code 的 Read 工具一样按文件类型分流：
- PDF → 用 pypdf 抽取每页文本（不再当 UTF-8 文本硬读）
- 普通文本 → 行切片（offset/limit 分页），编码多级回退（utf-8 / BOM / GB18030）
- 其它二进制 → 给出明确提示而不是抛 UnicodeDecodeError
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

from ._safety import resolve_workspace_path


_MAX_LIMIT = 2000
_DEFAULT_LIMIT = 200

# 单次结果字符预算（对齐 web_fetch / bash）；与 get_schema 的 max_result_size 保持一致。
_RESULT_BUDGET = 16000
# 读入内存的硬上限，避免超大文件 OOM。
_MAX_READ_BYTES = 5 * 1024 * 1024
# 默认整读（不分页）时，内容超过该字符数就改走有界返回 + 提示分页。
_FULL_RETURN_CHAR_CAP = 12000
# PDF 文本预算：留出余量给结构化元数据，避免被调度器整体截断成乱码。
_PDF_CHAR_BUDGET = 14000
# PDF 单次最多抽取的页数，避免超大文档塞爆上下文。
_MAX_PDF_PAGES = 100


def _is_pdf(path: Path) -> bool:
    """通过魔数 (%PDF) 判断，回退到扩展名。"""
    try:
        with open(path, "rb") as handle:
            if handle.read(5).startswith(b"%PDF"):
                return True
    except OSError:
        pass
    return path.suffix.lower() == ".pdf"


def _normalize(text: str) -> str:
    """去掉前导 BOM 并把换行统一成 \\n（对齐文本模式 open 的 universal newlines）。"""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _decode_bytes(raw: bytes, encoding: str) -> tuple[str | None, str, bool]:
    """把字节按编码解码，多级回退。

    返回 ``(text, used_encoding, replaced)``；若疑似二进制返回 ``(None, "", False)``。
    text 已做 BOM 去除与换行归一化。
    """
    # NUL 字节是二进制的强信号（GB18030 几乎能解码任意字节，必须先排除二进制）。
    if b"\x00" in raw[:8192]:
        return None, "", False

    candidates = [encoding]
    if encoding.lower().replace("-", "").replace("_", "") in ("utf8", ""):
        # 默认 utf-8：补充中文 Windows 常见的 GB18030。BOM 由 _normalize 统一去除。
        candidates += ["gb18030"]
    for enc in candidates:
        try:
            return _normalize(raw.decode(enc)), enc, False
        except (UnicodeDecodeError, LookupError):
            continue
    # 兜底：用请求编码强行解码并替换非法字节，明确标记。
    return _normalize(raw.decode(encoding, errors="replace")), f"{encoding}+replace", True


def _parse_pages(raw: Any, total: int) -> list[int]:
    """把 "1-5" / "3" / "10-20" 解析成 0-based 页索引列表（入参 1-based）。

    非法输入抛 ``ValueError``，由调用方转成友好错误。
    """
    if raw is None:
        return list(range(total))
    text = str(raw).strip()
    if not text:
        return list(range(total))
    try:
        if "-" in text:
            start_s, _, end_s = text.partition("-")
            start = int(start_s) if start_s.strip() else 1
            end = int(end_s) if end_s.strip() else total
        else:
            start = end = int(text)
    except ValueError as exc:
        raise ValueError(
            f"pages 格式非法: {text!r}；应形如 \"1-5\" / \"3\" / \"10-20\"（1-based）"
        ) from exc
    # clamp 到 [1, total] 并转 0-based
    start = max(1, start)
    end = min(total, end)
    return [i - 1 for i in range(start, end + 1)] if start <= end else []


def _read_pdf(resolved_path: Path, raw_pages: Any) -> dict[str, Any]:
    """抽取 PDF 文本，返回与文本路径一致的结果结构。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"error": "PDF 解析需要 pypdf，请先安装：pip install pypdf"}

    try:
        reader = PdfReader(str(resolved_path))
    except Exception as exc:  # noqa: BLE001 — pypdf 可能抛多种异常
        return {"error": f"Failed to parse PDF: {exc}"}

    total_pages = len(reader.pages)
    try:
        page_indices = _parse_pages(raw_pages, total_pages)
    except ValueError as exc:
        return {"error": str(exc)}

    page_truncated = False
    if len(page_indices) > _MAX_PDF_PAGES:
        page_indices = page_indices[:_MAX_PDF_PAGES]
        page_truncated = True

    chunks: list[str] = []
    extracted_chars = 0
    char_truncated = False
    for idx in page_indices:
        try:
            text = (reader.pages[idx].extract_text() or "").strip()
        except Exception as exc:  # noqa: BLE001
            text = f"[页面 {idx + 1} 抽取失败: {exc}]"
        chunk = f"--- Page {idx + 1} ---\n{text}"
        # 字符预算：超出就停在页边界，让模型用 pages 续读，而不是被调度器砍成乱码。
        if extracted_chars + len(chunk) > _PDF_CHAR_BUDGET and chunks:
            char_truncated = True
            break
        chunks.append(chunk)
        extracted_chars += len(chunk) + 2  # +2 为分隔符

    content = "\n\n".join(chunks)
    result: dict[str, Any] = {
        "content": content,
        "file_path": str(resolved_path),
        "size": len(content),
        "file_type": "pdf",
        "total_pages": total_pages,
        "returned_pages": len(chunks),
    }

    notes: list[str] = []
    if page_truncated:
        result["truncated"] = True
        notes.append(f"页数超过单次上限 {_MAX_PDF_PAGES}，仅返回前 {len(chunks)} 页。")
    if char_truncated:
        result["truncated"] = True
        last_page = page_indices[len(chunks) - 1] + 1 if chunks else 0
        notes.append(
            f"文本超出字符预算，截到第 {last_page} 页；用 pages 参数（如 "
            f"\"{last_page + 1}-{total_pages}\"）继续读取。"
        )
    # 每个 chunk 形如 "--- Page N ---\n<text>"；取换行后的正文判断是否全空。
    has_text = any(
        chunk.split("\n", 1)[1].strip() for chunk in chunks if "\n" in chunk
    )
    if chunks and not has_text:
        notes.append(
            "未抽取到任何文本，疑似扫描件/图片型 PDF，需要 OCR 或视觉模型处理。"
        )
    if notes:
        result["note"] = " ".join(notes)
    return result


class ReadFileCapability(CapabilityBase):
    """读取工作区内的文件内容。"""

    @property
    def name(self) -> str:
        return "read_file"

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
                    "file_path": {
                        "type": "string",
                        "description": "要读取的文件路径（仅允许工作区内路径）",
                    },
                    "encoding": {
                        "type": "string",
                        "description": (
                            "文件编码，默认 utf-8（解码失败时自动回退 BOM / GB18030）"
                        ),
                        "default": "utf-8",
                    },
                    "offset": {
                        "type": "integer",
                        "description": (
                            "起始行号 (0-based)。不传时读取整文件；传入时按行切片返回。"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"最多读取的行数，默认 {_DEFAULT_LIMIT}，最大 {_MAX_LIMIT}。"
                            "仅在传入 offset 或 limit 时启用分页模式。"
                        ),
                    },
                    "pages": {
                        "type": "string",
                        "description": (
                            "仅对 PDF 生效：页码范围（1-based），如 \"1-5\"、\"3\"、"
                            f"\"10-20\"；不传则读取全部（单次最多 {_MAX_PDF_PAGES} 页）。"
                        ),
                    },
                },
                "required": ["file_path"],
            },
            returns="文件内容字符串",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=_RESULT_BUDGET,
        )

    async def execute(self, **kwargs: Any) -> Any:
        file_path = kwargs.get("file_path", "")
        encoding = kwargs.get("encoding") or "utf-8"
        raw_offset = kwargs.get("offset")
        raw_limit = kwargs.get("limit")
        raw_pages = kwargs.get("pages")

        if not file_path:
            return {"error": "file_path is required"}

        try:
            resolved_path = resolve_workspace_path(file_path)
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to resolve path: {str(exc)}"}

        if not resolved_path.exists():
            return {"error": f"File not found: {file_path}"}
        if resolved_path.is_dir():
            return {"error": f"Path is a directory, not a file: {file_path}"}

        # PDF：按页抽取文本，而不是当 UTF-8 文本硬读。
        if _is_pdf(resolved_path):
            return _read_pdf(resolved_path, raw_pages)

        # 读入内存（带硬上限），随后多级解码。
        try:
            file_size = resolved_path.stat().st_size
            with open(resolved_path, "rb") as handle:
                raw = handle.read(_MAX_READ_BYTES)
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to read file: {str(exc)}"}

        bytes_truncated = file_size > _MAX_READ_BYTES

        content, used_encoding, replaced = _decode_bytes(raw, encoding)
        if content is None:
            return {
                "error": (
                    f"'{file_path}' 不是文本文件（含 NUL 字节，疑似二进制）。"
                    "若为 PDF 请确认扩展名/内容；其它二进制请改用专门的解析工具。"
                ),
                "file_path": str(resolved_path),
            }

        # Backward-compatible fast path: 既没分页、内容也不大时返回整文件。
        if (
            raw_offset is None
            and raw_limit is None
            and not bytes_truncated
            and len(content) <= _FULL_RETURN_CHAR_CAP
        ):
            result: dict[str, Any] = {
                "content": content,
                "file_path": str(resolved_path),
                "size": len(content),
            }
            if used_encoding != encoding:
                result["encoding"] = used_encoding
            if replaced:
                result["note"] = "原编码解码失败，已用替换字符兜底，内容可能不精确。"
            return result

        try:
            offset = int(raw_offset) if raw_offset is not None else 0
        except (TypeError, ValueError):
            return {"error": "offset must be an integer"}
        try:
            limit = int(raw_limit) if raw_limit is not None else _DEFAULT_LIMIT
        except (TypeError, ValueError):
            return {"error": "limit must be an integer"}

        if offset < 0:
            offset = 0
        if limit < 0:
            limit = 0
        if limit > _MAX_LIMIT:
            limit = _MAX_LIMIT

        # splitlines(keepends=True) preserves the original line terminators so
        # joining the slice yields a faithful slice of the original text.
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        sliced = lines[offset : offset + limit] if offset < total_lines else []
        sliced_content = "".join(sliced)

        result = {
            "content": sliced_content,
            "file_path": str(resolved_path),
            "size": len(sliced_content),
            "offset": offset,
            "limit": limit,
            "total_lines": total_lines,
            "returned_lines": len(sliced),
        }
        notes = []
        # 当默认整读因内容过大被迫走有界返回时，告诉模型如何续读。
        if raw_offset is None and raw_limit is None:
            notes.append(
                f"文件较大，默认仅返回前 {len(sliced)} 行（共 {total_lines} 行）；"
                "用 offset/limit 继续读取。"
            )
        if bytes_truncated:
            notes.append(
                f"文件超过 {_MAX_READ_BYTES // (1024 * 1024)}MB，仅读取了前半部分。"
            )
        if used_encoding != encoding:
            result["encoding"] = used_encoding
        if replaced:
            notes.append("原编码解码失败，已用替换字符兜底，内容可能不精确。")
        if notes:
            result["note"] = " ".join(notes)
        return result
