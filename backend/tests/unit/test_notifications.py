"""`<task-notification>` 格式化单测（v2 Phase C 支柱 8）"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.task.notifications import (
    format_task_notification,
    make_user_message,
)


def test_format_includes_xml_tags() -> None:
    xml = format_task_notification(
        {
            "task_id": "abc12345",
            "subagent_type": "coder",
            "status": "completed",
            "result": {"files": ["a.py"]},
            "usage": {"input_tokens": 100, "output_tokens": 50, "tool_uses": 2},
        }
    )
    assert xml.startswith("<task-notification>")
    assert xml.endswith("</task-notification>")
    assert "<task-id>abc12345</task-id>" in xml
    assert "<subagent-type>coder</subagent-type>" in xml
    assert "<status>completed</status>" in xml
    # 注意 result 内容会被 XML escape；JSON 化后 < > & 被转义
    assert "files" in xml
    assert "<input_tokens>100</input_tokens>" in xml
    assert "<output_tokens>50</output_tokens>" in xml
    assert "<tool_uses>2</tool_uses>" in xml


def test_format_truncates_long_result() -> None:
    huge = "x" * 5000
    xml = format_task_notification(
        {
            "task_id": "t1",
            "subagent_type": "coder",
            "status": "completed",
            "result": huge,
        }
    )
    # 截断后会带 truncated 提示
    assert "[truncated" in xml
    # 整体长度应在合理范围（result block ≤ 2000+padding）
    assert len(xml) < 5000


def test_format_failed_includes_error_block() -> None:
    xml = format_task_notification(
        {
            "task_id": "t2",
            "subagent_type": "reviewer",
            "status": "failed",
            "error": "review crashed: division by zero",
        }
    )
    assert "<status>failed</status>" in xml
    assert "<error>" in xml
    assert "division by zero" in xml


def test_format_killed_uses_default_summary() -> None:
    xml = format_task_notification(
        {
            "task_id": "t3-deadbeef-...",
            "subagent_type": "coder",
            "status": "killed",
        }
    )
    assert "<status>killed</status>" in xml
    assert "cancelled" in xml.lower() or "killed" in xml.lower()


def test_make_user_message_returns_user_role() -> None:
    msg = make_user_message(
        {"task_id": "t4", "subagent_type": "coder", "status": "completed"}
    )
    assert msg["role"] == "user"
    assert "<task-notification>" in msg["content"]


def test_xml_escape_protects_against_injection() -> None:
    xml = format_task_notification(
        {
            "task_id": "t5",
            "subagent_type": "coder",
            "status": "completed",
            "result": "<script>evil</script>",
        }
    )
    # 原始尖括号必须被转义，不能让模型把内嵌 result 当 XML
    assert "<script>evil</script>" not in xml
    assert "&lt;script&gt;" in xml
