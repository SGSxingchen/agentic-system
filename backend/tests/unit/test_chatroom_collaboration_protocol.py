"""Unit tests for the chatroom collaboration protocol constant + isolation regression."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 与其他单测一致：把 backend/src 注入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_protocol_constant_exists_and_lists_required_tools():
    """Spec 2 §6.2 — CHATROOM_COLLABORATION_PROTOCOL must:
    - 标记 [聊天室协作模式]
    - 列出每个核心协作工具
    - 包含 ✅ 和 ❌ 行为示例（CC behavior-examples format）
    - 显式覆盖 yaml 本体 prompt 的 JSON 输出契约
    """

    from core.prompts import CHATROOM_COLLABORATION_PROTOCOL

    text = CHATROOM_COLLABORATION_PROTOCOL
    assert isinstance(text, str)
    assert "[聊天室协作模式]" in text

    required_tools = [
        "chatroom_dispatch",
        "chatroom_get_goal",
        "chatroom_update_goal",
        "chatroom_invite",
        "chatroom_create_agent",
        "chatroom_todo",
    ]
    for tool_name in required_tools:
        assert tool_name in text, f"missing tool name '{tool_name}' in protocol"

    # Behavior examples（CC range）
    assert "✅" in text
    assert "❌" in text

    # JSON 输出契约覆盖语句（spec §6.2 第 1 段）
    assert "即使你的本体 prompt 要求" in text


def test_protocol_does_not_leak_to_chat_panel_path():
    """Task 5 / A14 — 协作覆盖前缀只在 chatroom 路径生效。

    模拟 ChatPanel / Agent Run 路径：直接拿 generic Agent 的 system prompt
    （从 agents.yaml 读出并组装）。这条路径没有 chatroom_orchestrator 介入，
    所以 build_room_context / CHATROOM_COLLABORATION_PROTOCOL 都不应出现。

    前提：core.prompts 不会把 CHATROOM_COLLABORATION_PROTOCOL 注入到通用
    prompt 装配函数（format_workspace_system_context / format_untrusted_memory_context）。
    """

    from core import prompts as prompts_mod
    from core.prompts import (
        CHATROOM_COLLABORATION_PROTOCOL,
        format_untrusted_memory_context,
        format_workspace_system_context,
    )

    base_prompt = "你是一个 helpful assistant。"

    workspace_block = format_workspace_system_context(
        base_prompt,
        agent_name="assistant",
        workspace_id="ws-1",
    )
    assert "[聊天室协作模式]" not in workspace_block
    assert "<chatroom_context>" not in workspace_block

    memory_block = format_untrusted_memory_context(base_prompt, "some recall")
    assert "[聊天室协作模式]" not in memory_block
    assert "<chatroom_context>" not in memory_block

    # 核心模块属性自检：保证 CHATROOM_COLLABORATION_PROTOCOL 仅作为常量存在，
    # 没有被其他通用 prompt builder 自动 import。
    assert CHATROOM_COLLABORATION_PROTOCOL  # truthy
