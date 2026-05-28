"""Task 8 — A10 ``update_agent_config`` 调用即生效的单一动词工具。

替代旧的 ``propose_agent_config_patch`` + ``apply_agent_config_patch`` 两段
式审批流程。审计靠 structlog ``config_change`` 日志，回溯靠 git。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import yaml

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from api.dependencies import set_reload_agent_fn
from capabilities.tools.agent_management import UpdateAgentConfigCapability


def _seed(config_dir: Path, agents: list[dict]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agents.yaml").write_text(
        yaml.dump({"agents": agents}), encoding="utf-8"
    )


@pytest.fixture
def empty_assistant(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    _seed(
        config_dir,
        [
            {
                "name": "assistant",
                "description": "old desc",
                "system_prompt": "你是助手",
                "tools": ["read_file"],
            }
        ],
    )
    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))

    async def _noop_reload():
        return None

    previous = None

    def _set(fn):  # capture previous reload fn for restore
        nonlocal previous
        previous = fn
        set_reload_agent_fn(fn)

    _set(_noop_reload)
    yield config_dir
    set_reload_agent_fn(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_update_agent_config_no_approval_required(empty_assistant):
    """A10：调用即生效，不需要 admin_approved / reviewer / admin_token。"""
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="assistant",
        patch={"description": "new desc by automation"},
    )
    assert result.get("success") is True, result
    on_disk = yaml.safe_load((empty_assistant / "agents.yaml").read_text())
    assistant = next(a for a in on_disk["agents"] if a["name"] == "assistant")
    assert assistant["description"] == "new desc by automation"


@pytest.mark.asyncio
async def test_update_agent_config_can_modify_tools(empty_assistant):
    """A10：tools 字段可直接改，包含 bash/dispatch_agent 等也允许。"""
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="assistant",
        patch={"tools": ["read_file", "write_file", "bash"]},
    )
    assert result.get("success") is True, result
    on_disk = yaml.safe_load((empty_assistant / "agents.yaml").read_text())
    assistant = next(a for a in on_disk["agents"] if a["name"] == "assistant")
    assert "bash" in assistant["tools"]


@pytest.mark.asyncio
async def test_update_agent_config_writes_audit_log(empty_assistant, caplog):
    """A10：调用结束后落 ``config_change`` 审计日志（agent / patch keys）。"""
    cap = UpdateAgentConfigCapability()
    with caplog.at_level(logging.INFO, logger="capabilities.tools.agent_management"):
        await cap.execute(
            agent_name="assistant",
            patch={"description": "audited update"},
        )
    audit_messages = [r.getMessage() for r in caplog.records]
    assert any("config_change" in m or "update_agent" in m for m in audit_messages), audit_messages


@pytest.mark.asyncio
async def test_update_agent_config_rejects_unknown_agent(empty_assistant):
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="ghost",
        patch={"description": "x"},
    )
    assert result.get("success") is False
    err_text = (
        result.get("error")
        or " ".join(result.get("errors") or [])
        or ""
    ).lower()
    assert "ghost" in err_text or "not found" in err_text


@pytest.mark.asyncio
async def test_update_agent_config_validates_patch_fields(empty_assistant):
    """patch 里出现非白名单字段时应返回 errors，不能写入。"""
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="assistant",
        patch={"forbidden_field_xyz": "abc"},
    )
    # 应当不写成功，errors 列表里包含字段问题
    assert result.get("success") is False
