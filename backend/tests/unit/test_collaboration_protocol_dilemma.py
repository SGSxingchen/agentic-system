"""A26 — CHATROOM_COLLABORATION_PROTOCOL 加困境处理段。

当 host（如 planner）卡住或方向错时，应主动 @ reviewer/coder 等专家协助，而不是
硬撑着自己回答。本测试 grep 协作前缀里必须含有的关键词。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保 src 在导入路径中（与其他单测一致）
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_protocol_includes_dilemma_section():
    """协作前缀必须包含【困境处理】段，并明确告诉 Agent 卡住时调 chatroom_dispatch。"""

    from core.prompts import CHATROOM_COLLABORATION_PROTOCOL

    assert "困境处理" in CHATROOM_COLLABORATION_PROTOCOL, (
        "协作前缀必须有【困境处理】小标题"
    )
    assert "chatroom_dispatch" in CHATROOM_COLLABORATION_PROTOCOL, (
        "困境处理段必须显式提到 chatroom_dispatch（叫专家发言）"
    )
    assert "不要装作没事" in CHATROOM_COLLABORATION_PROTOCOL, (
        "工具调用失败时必须显式说明，不能装作没事继续"
    )
