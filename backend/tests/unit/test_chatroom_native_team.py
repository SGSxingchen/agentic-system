"""聊天室原生协作团队 — 配置不变量测试。

Spec: docs/superpowers/specs/2026-06-01-chatroom-native-team-design.md
仅断言配置层面的不变量（不赌 LLM 输出、不需要 API key）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# 让 `from core.chatroom import ...` 可用（backend/src 加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"

NATIVE_TEAM = [
    "chat_planner",
    "chat_coder",
    "chat_reviewer",
    "facilitator",
    "researcher",
    "critic",
    "scribe",
]

# 这批 Agent 在 YAML 里允许引用的能力工具（chatroom_* 自治工具在房间内自动挂载，不在 YAML 列）
KNOWN_TOOLS = {
    "memory_search", "read_file", "write_file", "file_search",
    "web_search", "web_fetch", "code_parser", "json_tool",
    "static_analyzer", "test_runner", "text_processor",
    "datetime_tool", "calculator",
}


def _load_agents() -> dict:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return {a["name"]: a for a in data["agents"]}


def test_native_team_all_present():
    agents = _load_agents()
    for name in NATIVE_TEAM:
        assert name in agents, f"缺少聊天室原生 Agent: {name}"


@pytest.mark.parametrize("name", NATIVE_TEAM)
def test_native_agent_is_text(name):
    agents = _load_agents()
    assert agents[name]["output_format"] == "text", name


@pytest.mark.parametrize("name", NATIVE_TEAM)
def test_native_agent_has_no_json_contract(name):
    agents = _load_agents()
    prompt = agents[name]["system_prompt"]
    assert "严格输出纯 JSON" not in prompt, name
    assert "纯 JSON" not in prompt, name


@pytest.mark.parametrize("name", NATIVE_TEAM)
def test_native_agent_tools_known(name):
    agents = _load_agents()
    for tool in (agents[name].get("tools") or []):
        assert tool in KNOWN_TOOLS, f"{name} 引用未知工具 {tool}"


def test_default_host_is_facilitator():
    from core.chatroom import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["host_agent"] == "facilitator"


def test_build_room_context_lists_team_and_protocol():
    from core.chatroom import build_room_context
    room = {
        "topic": "测试房间",
        "goal": "验证上下文",
        "members": list(NATIVE_TEAM),
        "messages": [],
        "settings": {},
    }
    messages = build_room_context(room, "facilitator")
    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert "<protocol>" in system
    for name in NATIVE_TEAM:
        assert name in system, name
