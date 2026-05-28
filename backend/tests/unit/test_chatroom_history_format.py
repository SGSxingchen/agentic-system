"""Unit tests for chatroom history XML formatting + role assignment fix.

Task 2 (reality-check) wrote the xfail test that documents the current
role-confusion bug — non-self agent messages were returned with role=assistant,
which makes the LM confuse other speakers with its own past turns. Task 3
flips the assertion live and adds the rest of the format coverage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# 与其他单测一致：把 backend/src 注入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _msg(**overrides):
    base = {
        "id": "m-1",
        "sender": "agent:reviewer",
        "content": "hello",
        "status": "done",
        "created_at": "2026-05-28T00:00:00Z",
        "mentions": [],
        "parent_message_id": None,
    }
    base.update(overrides)
    return base


def test_other_agents_use_user_role_after_fix():
    """Task 3 flips the Task 2 xfail: other agents must use role=user."""

    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(sender="agent:reviewer"),
        target_agent_name="coder",
    )
    assert formatted is not None
    assert formatted["role"] == "user"


def test_self_agent_uses_assistant_role_no_prefix():
    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(sender="agent:reviewer", content="hello"),
        target_agent_name="reviewer",
    )
    assert formatted == {"role": "assistant", "content": "hello"}


def test_other_agent_uses_user_role_with_xml_metadata():
    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(
            id="m-7",
            sender="agent:reviewer",
            content="hello",
            mentions=["coder"],
            parent_message_id="m-3",
            created_at="2026-05-28T01:02:03Z",
        ),
        target_agent_name="coder",
    )
    assert formatted is not None
    assert formatted["role"] == "user"
    pattern = (
        r'^<msg id="m-7" from="reviewer" at="2026-05-28T01:02:03Z" '
        r'mentions="coder" parent="m-3">hello</msg>$'
    )
    assert re.match(pattern, formatted["content"]), formatted["content"]


def test_user_message_xml_includes_mentions_when_present():
    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(
            id="u-1",
            sender="user",
            content="please review",
            mentions=["coder"],
            created_at="2026-05-28T00:00:00Z",
        ),
        target_agent_name="reviewer",
    )
    assert formatted["role"] == "user"
    assert 'from="user"' in formatted["content"]
    assert 'mentions="coder"' in formatted["content"]


def test_user_message_xml_omits_mentions_when_absent():
    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(
            id="u-2",
            sender="user",
            content="hi everyone",
            mentions=[],
        ),
        target_agent_name="coder",
    )
    assert formatted["role"] == "user"
    assert "mentions=" not in formatted["content"]
    assert 'from="user"' in formatted["content"]


def test_system_message_uses_system_event_tag():
    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(
            id="s-1",
            sender="system",
            content="member joined",
            created_at="2026-05-28T00:00:00Z",
        ),
        target_agent_name="coder",
    )
    assert formatted["role"] == "user"
    assert re.match(
        r'^<system_event at="2026-05-28T00:00:00Z">member joined</system_event>$',
        formatted["content"],
    )


def test_pending_streaming_failed_status_skipped():
    from core.chatroom import _format_history_message

    for status in ("pending", "streaming", "failed"):
        formatted = _format_history_message(
            _msg(status=status), target_agent_name="coder"
        )
        assert formatted is None, f"status={status} should be skipped"


def test_unknown_sender_falls_back_to_unknown_msg():
    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(sender="weird", content="??"),
        target_agent_name="coder",
    )
    assert formatted["role"] == "user"
    assert formatted["content"].startswith('<unknown_msg from="weird"')


def test_xml_escapes_content_special_chars():
    """`<` `>` `&` 必须转义防止 XML 注入。"""

    from core.chatroom import _format_history_message

    formatted = _format_history_message(
        _msg(
            id="m-9",
            sender="agent:reviewer",
            content="if a < b & b > c",
        ),
        target_agent_name="coder",
    )
    assert formatted is not None
    body = formatted["content"]
    assert "&lt;" in body
    assert "&gt;" in body
    assert "&amp;" in body
    # 原始字符不应直接出现
    assert " < " not in body
    assert " > " not in body

