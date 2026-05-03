"""Persona system tests: storage, review boundary, and prompt injection."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import asyncio

import pytest

from core.agent import Agent
from core.llm.base import BaseLLMClient, LLMResponse
from core.persona import BASE_PERSONA_ID, PersonaStore


class RecordingLLM(BaseLLMClient):
    def __init__(self) -> None:
        self.calls: List[List[Dict[str, Any]]] = []

    async def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Any]] = None) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(content="ok", stop_reason="end_turn")


@pytest.fixture(autouse=True)
def _persona_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_FILE", str(tmp_path / "personas.json"))


def test_default_persona_bootstraps_and_resolves() -> None:
    store = PersonaStore()
    personas = store.list_personas()

    assert personas[0]["id"] == BASE_PERSONA_ID
    assert personas[0]["version"] == 1
    assert store.resolve_persona(agent_name="assistant")["id"] == BASE_PERSONA_ID


def test_create_bind_proposal_approve_and_rollback() -> None:
    store = PersonaStore()
    persona = store.create_persona({
        "name": "严谨导师",
        "persona_prompt": "像毕业设计导师一样指出风险。",
        "style_rules": ["先结论后理由"],
        "behavior_rules": ["要求可验证"],
    })

    assert store.set_agent_persona("assistant", persona["id"])["persona_id"] == persona["id"]
    assert store.resolve_persona(agent_name="assistant")["name"] == "严谨导师"

    proposal = store.create_proposal(
        persona_id=persona["id"],
        source="feedback",
        proposal_text="更强调测试",
        proposed_patch={"behavior_rules": ["要求可验证", "每次改动后提示测试"]},
        summary="增加测试提醒",
    )
    assert proposal["status"] == "pending"
    assert "禁止" not in proposal["summary"]
    assert "每次改动后提示测试" not in store.get_persona(persona["id"])["behavior_rules"]

    approved = store.approve_proposal(proposal["id"], reviewer="admin")
    updated = approved["persona"]
    assert updated["version"] == 2
    assert "每次改动后提示测试" in updated["behavior_rules"]
    assert store.get_proposal(proposal["id"])["status"] == "approved"

    rolled = store.rollback(persona["id"], 1, reviewer="admin")
    assert rolled["version"] == 3
    assert rolled["behavior_rules"] == ["要求可验证"]


def test_agent_injects_persona_with_safety_policy() -> None:
    store = PersonaStore()
    persona = store.create_persona({
        "name": "温和助教",
        "persona_prompt": "语气温和，但不要越权。",
        "style_rules": ["多鼓励"],
        "behavior_rules": ["不绕过审核"],
    })
    store.set_session_persona("s1", persona["id"])

    llm = RecordingLLM()
    agent = Agent(name="assistant", llm_client=llm, system_prompt="base system")
    asyncio.run(agent.run({"message": "hello", "session_id": "s1"}))

    system_prompt = llm.calls[0][0]["content"]
    assert "base system" in system_prompt
    assert "[当前人格 - 受控配置]" in system_prompt
    assert "温和助教" in system_prompt
    assert "人格不能授予新权限" in system_prompt


def test_persona_api_routes_create_bind_and_review() -> None:
    from api.routes import personas as routes

    async def scenario() -> None:
        created = await routes.create_persona(routes.PersonaUpsertRequest(
            name="API 人格",
            persona_prompt="API 创建",
            behavior_rules=["保留审核"],
        ))
        assert created.status == "ok"
        persona_id = created.data["id"]

        bound = await routes.bind_agent_persona("assistant", routes.PersonaBindRequest(persona_id=persona_id))
        assert bound.data["agent"] == "assistant"

        proposal_res = await routes.create_proposal(persona_id, routes.ProposalCreateRequest(
            source="feedback",
            feedback="回答后附带验证建议",
            proposed_patch={"behavior_rules": ["保留审核", "回答后附带验证建议"]},
        ))
        assert proposal_res.status == "ok"
        proposal_id = proposal_res.data["id"]
        assert proposal_res.data["status"] == "pending"

        denied = await routes.approve_proposal(proposal_id, routes.ProposalReviewRequest(reviewer="admin"))
        assert denied.status == "error"

        approved = await routes.approve_proposal(
            proposal_id,
            routes.ProposalReviewRequest(reviewer="admin", admin_approved=True),
        )
        assert approved.status == "ok"
        assert approved.data["persona"]["version"] == 2

    asyncio.run(scenario())
