"""A22 — agent_manager REST 路由层硬保护已删除（PUT/DELETE/MCP import 都允许）。

PR #31 A10 拆掉了 agent_management.py 工具层的三段式审批，但 routes/agents.py
还残留 PROTECTED_AGENT_NAMES 集合 + agent_manager 硬编码拒绝。本测试验证这些
拦截全部下线，所有写路径走 _save_config_and_reload + config_change 审计日志。
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

# 确保 src 在导入路径中（与其他单测一致）
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def stub_agent_yaml(monkeypatch):
    """Stub agents.yaml + _save_config_and_reload，避免真写盘 / 真热重载。"""

    from api.routes import agents as agent_routes

    initial_config = {
        "agents": [
            {
                "name": "agent_manager",
                "description": "原描述",
                "prompt": "原 prompt",
                "model": "gpt-4",
                "tools": [],
            }
        ]
    }
    state = {"data": deepcopy(initial_config), "saved": None}

    def fake_load(name: str):
        return deepcopy(state["data"])

    async def fake_save(data, previous_data):
        state["saved"] = deepcopy(data)
        state["data"] = deepcopy(data)

    monkeypatch.setattr(agent_routes, "load_single_yaml", fake_load)
    monkeypatch.setattr(agent_routes, "_save_config_and_reload", fake_save)

    return state


async def test_put_agent_manager_no_longer_blocked(stub_agent_yaml):
    """PUT /api/agents/agent_manager 改 description 应该 200 + yaml 实际写入。"""

    from api.routes import agents as agent_routes
    from api.schemas import AgentUpdateRequest

    response = await agent_routes.update_agent(
        "agent_manager",
        AgentUpdateRequest(description="A22 之后允许改描述"),
    )

    assert response.status == "ok", f"PUT 应被允许：{response.message}"
    saved = stub_agent_yaml["saved"]
    assert saved is not None, "PUT 必须实际触发 _save_config_and_reload"
    target = next(
        a for a in saved["agents"] if a.get("name") == "agent_manager"
    )
    assert target["description"] == "A22 之后允许改描述"


async def test_delete_agent_manager_no_longer_blocked(stub_agent_yaml):
    """DELETE /api/agents/agent_manager 应允许（API 层不再硬拦）。"""

    from api.routes import agents as agent_routes

    response = await agent_routes.delete_agent("agent_manager")

    assert response.status == "ok", f"DELETE 应被允许：{response.message}"
    saved = stub_agent_yaml["saved"]
    assert saved is not None, "DELETE 必须实际触发 _save_config_and_reload"
    names = [a.get("name") for a in saved["agents"]]
    assert "agent_manager" not in names, "agent_manager 应已从 yaml 移除"


def test_protected_agent_names_constant_removed():
    """PROTECTED_AGENT_NAMES 模块级常量必须删除（A22 §1.2 第一条）。"""

    from api.routes import agents as agent_routes

    assert not hasattr(
        agent_routes, "PROTECTED_AGENT_NAMES"
    ), "PROTECTED_AGENT_NAMES 应已删除（A10 哲学：调用即生效 + 审计代替审批）"


def test_default_bindable_agent_roles_still_imported():
    """DEFAULT_BINDABLE_AGENT_ROLES 仍要保留（用作 persona 绑定列表）。"""

    from api.routes import agents as agent_routes

    assert hasattr(agent_routes, "DEFAULT_BINDABLE_AGENT_ROLES"), (
        "DEFAULT_BINDABLE_AGENT_ROLES 仅用于 persona 绑定，不能被一起删掉"
    )
