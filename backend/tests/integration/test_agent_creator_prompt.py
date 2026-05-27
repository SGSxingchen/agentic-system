"""Task 7 — agent_creator prompt 改为'主动挂工具'。

Plan §P1 / A4：HIGH_RISK_TOOLS 默认放开后，agent_creator 不该再写"不给
新 Agent 授予 bash"，而是主动挂上一套覆盖大多数动手任务的默认工具栈。
"""

from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"


def _load_creator() -> dict:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return next(a for a in data["agents"] if a["name"] == "agent_creator")


def test_agent_creator_prompt_encourages_full_toolstack():
    """prompt 必须主动指引挂工具，而不是回避高风险工具。"""
    creator = _load_creator()
    prompt = creator["system_prompt"]
    # 必须出现"主动"挂工具的语义关键词
    assert "主动" in prompt, prompt
    # 必须明确把 bash / write_file 等纳入默认工具栈讨论范围
    assert "bash" in prompt
    assert "write_file" in prompt
    # 必须移除"不给 ... bash"这类一刀切硬约束（应该改成"按职责挂"）
    assert "不给新 Agent 授予 bash" not in prompt


def test_agent_creator_no_longer_forbids_high_risk_tools():
    """旧的高风险硬约束行整体消失。"""
    creator = _load_creator()
    prompt = creator["system_prompt"]
    forbidden_phrase = "不给新 Agent 授予 bash / write_file / dispatch_agent"
    assert forbidden_phrase not in prompt


def test_agent_creator_entry_still_present():
    """红线：agents.yaml 不能删除 agent_creator 整条。"""
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    names = [a["name"] for a in data["agents"]]
    assert "agent_creator" in names
