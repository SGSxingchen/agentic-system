"""Unit tests for chatroom history XML formatting + role assignment fix.

Task 2 (reality-check) writes the xfail test that documents the current
role-confusion bug — non-self agent messages are returned with role=assistant,
which makes the LM confuse other speakers with its own past turns. Task 3
flips the assertion live and adds the rest of the format coverage.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 与其他单测一致：把 backend/src 注入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.mark.xfail(
    strict=True,
    reason="will be fixed in Task 5 / A15 history rewrite",
)
def test_current_state_other_agents_use_assistant_role():
    """Reality-check (Task 2): document the role-confusion bug.

    Current implementation incorrectly returns ``role=assistant`` for messages
    from OTHER agents (not the target). LM multi-turn training assumes
    assistant role only contains the model's own previous turns, so this
    causes severe role confusion.

    Expected post-fix behavior: other agents use ``role=user`` so the LM
    cleanly separates "my own past output" from "what other speakers said".
    The xfail decorator is removed in Task 3 once the rewrite lands.
    """

    from core.chatroom import _format_history_message

    other_message = {
        "id": "m-1",
        "sender": "agent:reviewer",
        "content": "hello",
        "status": "done",
        "created_at": "2026-05-28T00:00:00Z",
        "mentions": [],
        "parent_message_id": None,
    }
    formatted = _format_history_message(other_message, target_agent_name="coder")
    assert formatted is not None
    assert formatted["role"] == "user", (
        "other agents must use role=user; current code returns role=assistant "
        "which causes LM role confusion."
    )
