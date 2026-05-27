"""Task 10 — A10 ``update_persona`` 替代 propose+approve persona 流程。

Plan §P1 / A10：persona 修改也走"调用即生效，审计走日志"模式。新工具
``update_persona`` 直接接 persona_id + patch 写盘并发版本；不再要求
admin_approved / reviewer / admin_token。``PersonaStore.list_proposals``
存量数据保留（R7 历史归档语义），UI 改"历史/归档"提示。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.update_persona import UpdatePersonaCapability


@pytest.fixture
def persona_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_FILE", str(tmp_path / "personas.json"))
    from core.persona import PersonaStore

    store = PersonaStore()
    seed = store.create_persona(
        {
            "id": "test_persona_a10",
            "name": "测试人格",
            "description": "Task 10 测试用",
            "persona_prompt": "原始 prompt",
        }
    )
    return seed


@pytest.mark.asyncio
async def test_update_persona_no_approval_required(persona_store):
    """A10：update_persona 不需要 admin_approved / reviewer。"""
    cap = UpdatePersonaCapability()
    result = await cap.execute(
        persona_id="test_persona_a10",
        patch={"description": "经过 update_persona 修改"},
    )
    assert result.get("success") is True, result
    assert result["persona"]["description"] == "经过 update_persona 修改"


@pytest.mark.asyncio
async def test_update_persona_can_change_prompt(persona_store):
    cap = UpdatePersonaCapability()
    result = await cap.execute(
        persona_id="test_persona_a10",
        patch={"persona_prompt": "更新后的 prompt 内容"},
    )
    assert result.get("success") is True
    assert result["persona"]["persona_prompt"] == "更新后的 prompt 内容"


@pytest.mark.asyncio
async def test_update_persona_writes_audit_log(persona_store, caplog):
    cap = UpdatePersonaCapability()
    with caplog.at_level(logging.INFO, logger="capabilities.tools.update_persona"):
        await cap.execute(
            persona_id="test_persona_a10",
            patch={"description": "audited"},
        )
    audit_messages = [r.getMessage() for r in caplog.records]
    assert any("config_change" in m or "update_persona" in m for m in audit_messages), audit_messages


@pytest.mark.asyncio
async def test_update_persona_rejects_unknown_id(persona_store):
    cap = UpdatePersonaCapability()
    result = await cap.execute(persona_id="ghost_id", patch={"description": "x"})
    assert result.get("success") is False
    err = (result.get("error") or "").lower()
    assert "ghost_id" in err or "not found" in err
