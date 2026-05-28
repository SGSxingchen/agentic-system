"""Task 6 — A4 evolution_config 高风险硬拒绝改成 forbidden_tools 配置项。

Plan §P1 / A4：
- create_agent_config 默认放开 HIGH_RISK_TOOLS（bash / write_file / dispatch_agent / ...）。
- 部署方仍可在 system.yaml 设置 ``agent_creation.forbidden_tools`` 锁特定工具。
- 写入时落 structlog ``config_change`` 审计日志。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.evolution_config import CreateAgentConfigCapability


def _seed_agents_yaml(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agents.yaml").write_text(
        yaml.dump({"agents": [{"name": "assistant", "tools": []}]}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_agent_creator_can_grant_bash(tmp_path, monkeypatch):
    """A4：默认 forbidden_tools=[] 时 bash + dispatch_agent 都该能挂。"""
    config_dir = tmp_path / "config"
    _seed_agents_yaml(config_dir)
    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))

    tool = CreateAgentConfigCapability()
    result = await tool.execute(
        name="test_runner_a4",
        description="跑测试的运行器",
        system_prompt="你是测试 runner，需要执行命令并写文件。",
        tools=["bash", "write_file", "dispatch_agent"],
    )
    assert result.get("success") is True, result
    assert "bash" in result["agent"]["tools"]
    assert "dispatch_agent" in result["agent"]["tools"]


@pytest.mark.asyncio
async def test_forbidden_tools_block_rejects(tmp_path, monkeypatch):
    """A4：system.yaml 配置了 forbidden_tools 后仍能拒绝。"""
    config_dir = tmp_path / "config"
    _seed_agents_yaml(config_dir)
    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))

    fake_cfg = SimpleNamespace(
        agent_creation=SimpleNamespace(forbidden_tools=["bash"])
    )
    monkeypatch.setattr(
        "capabilities.tools.evolution_config._get_system_config",
        lambda: fake_cfg,
    )

    tool = CreateAgentConfigCapability()
    result = await tool.execute(
        name="x_blocked",
        description="y",
        system_prompt="z",
        tools=["bash"],
    )
    assert "error" in result
    assert "forbidden" in result["error"].lower() or "bash" in result["error"]


@pytest.mark.asyncio
async def test_create_agent_config_writes_audit_log(tmp_path, monkeypatch, caplog):
    """A4：写入成功后落 structlog ``config_change`` 审计行。"""
    config_dir = tmp_path / "config"
    _seed_agents_yaml(config_dir)
    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))

    tool = CreateAgentConfigCapability()
    with caplog.at_level("INFO", logger="capabilities.tools.evolution_config"):
        result = await tool.execute(
            name="auditor_a4",
            description="审计测试用",
            system_prompt="测试 audit log 的 Agent。",
            tools=["read_file"],
        )
    assert result.get("success") is True
    audit_messages = [r.getMessage() for r in caplog.records]
    assert any("config_change" in m or "create_agent" in m for m in audit_messages), audit_messages
