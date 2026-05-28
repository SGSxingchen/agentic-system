"""Task 9 — A10 删除 propose/apply 两段式审批工具。

Plan §P1 / A10：``update_agent_config`` 替代了 propose+apply 两段式后，
旧的 ProposeAgentConfigPatchCapability / ApplyAgentConfigPatchCapability /
``_admin_decision`` 等死代码必须清掉，并在 agent_manager 工具列表里把
``propose_agent_config_patch`` / ``apply_agent_config_patch`` 替换为
``update_agent_config``。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


CAPABILITIES_YAML = Path(__file__).resolve().parents[3] / "config" / "capabilities.yaml"
AGENTS_YAML = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def test_propose_apply_capabilities_removed_from_module():
    from capabilities.tools import agent_management

    assert not hasattr(agent_management, "ProposeAgentConfigPatchCapability")
    assert not hasattr(agent_management, "ApplyAgentConfigPatchCapability")
    assert not hasattr(agent_management, "_admin_decision")


def test_propose_apply_removed_from_capabilities_yaml():
    data = yaml.safe_load(CAPABILITIES_YAML.read_text(encoding="utf-8"))
    names = {c["name"] for c in data["capabilities"]}
    assert "propose_agent_config_patch" not in names
    assert "apply_agent_config_patch" not in names
    assert "update_agent_config" in names


def test_agent_manager_tools_list_uses_update_agent_config():
    data = yaml.safe_load(AGENTS_YAML.read_text(encoding="utf-8"))
    mgr = next(a for a in data["agents"] if a["name"] == "agent_manager")
    tools = mgr.get("tools") or []
    assert "update_agent_config" in tools
    assert "propose_agent_config_patch" not in tools
    assert "apply_agent_config_patch" not in tools


def test_agent_manager_entry_still_exists():
    """红线：不能删除 agent_manager 整条，只换工具列表。"""
    data = yaml.safe_load(AGENTS_YAML.read_text(encoding="utf-8"))
    names = [a["name"] for a in data["agents"]]
    assert "agent_manager" in names
