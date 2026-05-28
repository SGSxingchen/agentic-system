"""Task 13 — P1 (A4 + A10) 自由化端到端集成测试。

覆盖：
- A4：agent_creator 路径的 create_agent_config 能挂 bash + dispatch_agent 全套高风险工具
- A10：update_agent_config 调用即生效（不要 admin_approved/reviewer）
- A10：dispatch_agent 嵌套深度 4 仍允许，5 才拒
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from api.dependencies import set_reload_agent_fn
from capabilities.tools.agent_management import UpdateAgentConfigCapability
from capabilities.tools.dispatch_agent import DispatchAgentCapability
from capabilities.tools.evolution_config import CreateAgentConfigCapability
from core.task import reset_dispatch_depth, set_dispatch_depth


def _seed_assistant_yaml(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agents.yaml").write_text(
        yaml.dump({"agents": [{"name": "assistant", "tools": []}]}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_e2e_agent_creator_grants_full_toolstack(tmp_path, monkeypatch):
    """A4 闭环：create_agent_config 能创建带 bash + dispatch_agent 的新 Agent。"""
    config_dir = tmp_path / "config"
    _seed_assistant_yaml(config_dir)
    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))

    cap = CreateAgentConfigCapability()
    result = await cap.execute(
        name="frontend_designer_e2e",
        description="前端设计专家",
        system_prompt="你写前端代码并调用 bash 运行 npm。",
        tools=[
            "bash",
            "write_file",
            "dispatch_agent",
            "web_fetch",
            "web_search",
            "read_file",
        ],
    )
    assert result.get("success") is True, result
    assert {"bash", "write_file", "dispatch_agent"}.issubset(set(result["agent"]["tools"]))


@pytest.mark.asyncio
async def test_e2e_agent_self_modify_via_update(tmp_path, monkeypatch):
    """A10 闭环：update_agent_config 直接给已存在的 Agent 加工具。"""
    config_dir = tmp_path / "config"
    _seed_assistant_yaml(config_dir)
    # 先创建一个 e2e 测试用 Agent
    (config_dir / "agents.yaml").write_text(
        yaml.dump(
            {
                "agents": [
                    {
                        "name": "assistant",
                        "tools": [],
                    },
                    {
                        "name": "frontend_designer_e2e",
                        "description": "前端设计专家",
                        "system_prompt": "你写前端代码",
                        "tools": ["read_file"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))

    async def _noop_reload():
        return None

    set_reload_agent_fn(_noop_reload)
    try:
        cap = UpdateAgentConfigCapability()
        result = await cap.execute(
            agent_name="frontend_designer_e2e",
            patch={"tools": ["bash", "write_file", "json_tool"]},
        )
        assert result.get("success") is True, result
        on_disk = yaml.safe_load((config_dir / "agents.yaml").read_text())
        target = next(a for a in on_disk["agents"] if a["name"] == "frontend_designer_e2e")
        assert {"bash", "write_file", "json_tool"} == set(target["tools"])
    finally:
        set_reload_agent_fn(None)  # type: ignore[arg-type]


def test_e2e_dispatch_depth_4_allowed_5_denied():
    """A10 闭环：dispatch_agent 默认允许嵌套到 4 层（depth=4 仍 allow），depth=5 拒。"""
    cap = DispatchAgentCapability()

    token = set_dispatch_depth(4)
    try:
        outcome_4 = cap.check_permissions(subagent_type="coder", prompt="x")
    finally:
        reset_dispatch_depth(token)
    assert outcome_4["decision"] == "allow"

    token = set_dispatch_depth(5)
    try:
        outcome_5 = cap.check_permissions(subagent_type="coder", prompt="x")
    finally:
        reset_dispatch_depth(token)
    assert outcome_5["decision"] == "deny"
