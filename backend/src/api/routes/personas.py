"""Persona management and guarded self-iteration routes."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from core.persona import BASE_PERSONA_ID, PersonaBindingService, PersonaStore
from ..dependencies import get_llm_client
from ..schemas import APIResponse

router = APIRouter(prefix="/api/personas", tags=["personas"])


class PersonaUpsertRequest(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1)
    description: str = ""
    persona_prompt: str = Field(default="", description="人格/system 提示词片段")
    style_rules: list[str] = Field(default_factory=list)
    behavior_rules: list[str] = Field(default_factory=list)
    permission_boundary: str = "人格不得扩大系统级权限。"
    status: str = "active"


class PersonaUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    persona_prompt: Optional[str] = None
    style_rules: Optional[list[str]] = None
    behavior_rules: Optional[list[str]] = None
    permission_boundary: Optional[str] = None
    status: Optional[str] = None


class PersonaBindRequest(BaseModel):
    persona_id: str = Field(default=BASE_PERSONA_ID)


class ProposalCreateRequest(BaseModel):
    source: str = Field(default="admin_instruction", description="feedback | admin_instruction | reflection")
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    reflection_id: Optional[str] = None
    feedback: str = ""
    proposal_text: Optional[str] = Field(default=None, description="可选：管理员手写建议说明")
    proposed_patch: Optional[dict[str, Any]] = Field(default=None, description="可选：明确字段补丁")


class ProposalReviewRequest(BaseModel):
    reviewer: str = Field(default="local-admin")
    note: str = ""
    admin_approved: bool = Field(default=False, description="批准时必须显式为 true，防误触")


class RollbackRequest(BaseModel):
    version: int = Field(..., ge=1)
    reviewer: str = "local-admin"
    note: str = ""
    admin_approved: bool = Field(default=False)


def _store() -> PersonaStore:
    return PersonaStore()


def _require_admin(
    reviewer: str,
    *,
    x_admin_token: Optional[str] = None,
    x_admin_user: Optional[str] = None,
) -> str:
    """Central admin boundary for persona mutation/review endpoints.

    If PERSONA_ADMIN_TOKEN is configured, callers must provide the matching
    X-Admin-Token header.  In local thesis/demo mode no token is configured;
    routes still require explicit reviewer/admin_approved fields for approval
    actions so persona iteration cannot silently overwrite content.
    """

    def _clean(value: Any) -> str:
        return value if isinstance(value, str) else ""

    expected = os.getenv("PERSONA_ADMIN_TOKEN", "").strip()
    token = _clean(x_admin_token)
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="admin token required")
    user = _clean(x_admin_user) or _clean(reviewer) or "local-admin"
    return user.strip() or "local-admin"


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def _fallback_patch(persona: dict[str, Any], req: ProposalCreateRequest) -> tuple[str, dict[str, Any], str]:
    feedback = req.feedback.strip() or req.proposal_text or ""
    current_rules = persona.get("behavior_rules") or []
    new_rules = list(current_rules)
    if feedback and not any(feedback in item for item in new_rules):
        new_rules.append(f"迭代候选：{feedback[:160]}")
    patch = req.proposed_patch or {"behavior_rules": new_rules}
    text = req.proposal_text or f"根据 {req.source} 生成人格迭代建议：{feedback[:300]}"
    return text, patch, "启发式建议：后端未调用 LLM 或 LLM 未返回可解析 JSON；建议仍需管理员审核。"


async def _generate_patch(persona: dict[str, Any], req: ProposalCreateRequest) -> tuple[str, dict[str, Any], str]:
    if req.proposed_patch:
        return req.proposal_text or "管理员提交了明确的人格补丁。", req.proposed_patch, "管理员手写补丁，等待审核。"

    llm = get_llm_client()
    if not llm:
        return _fallback_patch(persona, req)

    system = (
        "你是人格迭代建议生成器。只能提出待审核建议，不能声称已生效。"
        "不得扩大权限、不得绕过管理员审核、不得修改系统级安全边界。"
        "只输出纯 JSON: {\"proposal_text\": str, \"proposed_patch\": object, \"summary\": str}. "
        "proposed_patch 只允许 name/description/persona_prompt/style_rules/behavior_rules/permission_boundary/status 字段。"
    )
    user = {
        "current_persona": persona,
        "source": req.source,
        "session_id": req.session_id,
        "message_id": req.message_id,
        "reflection_id": req.reflection_id,
        "feedback_or_instruction": req.feedback,
    }
    try:
        response = await llm.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ])
        payload = json.loads(_strip_json_fence(response.content or ""))
        patch = payload.get("proposed_patch") if isinstance(payload, dict) else None
        if isinstance(patch, dict):
            return (
                str(payload.get("proposal_text") or req.feedback or "人格迭代建议"),
                patch,
                str(payload.get("summary") or "LLM 生成的人格迭代建议，等待审核。"),
            )
    except Exception:
        pass
    return _fallback_patch(persona, req)


@router.get("", response_model=APIResponse)
async def list_personas(include_archived: bool = Query(default=False)) -> APIResponse:
    return APIResponse(status="ok", data=_store().list_personas(include_archived=include_archived))


@router.post("", response_model=APIResponse)
async def create_persona(
    req: PersonaUpsertRequest,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    _require_admin("local-admin", x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    try:
        persona = _store().create_persona(req.model_dump(exclude_none=True))
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    return APIResponse(status="ok", data=persona)


@router.get("/bindings", response_model=APIResponse)
async def get_bindings() -> APIResponse:
    """Compatibility alias. Prefer /api/agents/persona-bindings for Agent/session bindings."""

    return APIResponse(status="ok", data=PersonaBindingService().get_bindings())


@router.put("/bindings/agents/{agent_name}", response_model=APIResponse)
async def bind_agent_persona(agent_name: str, req: PersonaBindRequest) -> APIResponse:
    """Compatibility alias. Prefer PUT /api/agents/persona-bindings/agents/{agent_name}."""

    try:
        binding = PersonaBindingService().bind_agent(agent_name, req.persona_id)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    return APIResponse(status="ok", data=binding)


@router.put("/bindings/sessions/{session_id}", response_model=APIResponse)
async def bind_session_persona(session_id: str, req: PersonaBindRequest) -> APIResponse:
    """Compatibility alias. Prefer PUT /api/agents/persona-bindings/sessions/{session_id}."""

    try:
        binding = PersonaBindingService().bind_session(session_id, req.persona_id)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    return APIResponse(status="ok", data=binding)


@router.get("/proposals", response_model=APIResponse)
async def list_proposals(status: Optional[str] = None, persona_id: Optional[str] = None) -> APIResponse:
    return APIResponse(status="ok", data=_store().list_proposals(status=status, persona_id=persona_id))


@router.get("/proposals/{proposal_id}", response_model=APIResponse)
async def get_proposal(proposal_id: str) -> APIResponse:
    proposal = _store().get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="proposal not found")
    return APIResponse(status="ok", data=proposal)


@router.post("/proposals/{proposal_id}/approve", response_model=APIResponse)
async def approve_proposal(
    proposal_id: str,
    req: ProposalReviewRequest,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    if not req.admin_approved:
        return APIResponse(status="error", message="批准人格迭代必须显式 admin_approved=true")
    reviewer = _require_admin(req.reviewer, x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    try:
        result = _store().approve_proposal(proposal_id, reviewer=reviewer, note=req.note)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="proposal not found")
    return APIResponse(status="ok", data=result)


@router.post("/proposals/{proposal_id}/reject", response_model=APIResponse)
async def reject_proposal(
    proposal_id: str,
    req: ProposalReviewRequest,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    reviewer = _require_admin(req.reviewer, x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    try:
        proposal = _store().reject_proposal(proposal_id, reviewer=reviewer, note=req.note)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    if not proposal:
        raise HTTPException(status_code=404, detail="proposal not found")
    return APIResponse(status="ok", data=proposal)


@router.get("/{persona_id}", response_model=APIResponse)
async def get_persona(persona_id: str) -> APIResponse:
    persona = _store().get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return APIResponse(status="ok", data=persona)


@router.put("/{persona_id}", response_model=APIResponse)
async def update_persona(
    persona_id: str,
    req: PersonaUpdateRequest,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    _require_admin("local-admin", x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    persona = _store().update_persona(persona_id, req.model_dump(exclude_none=True))
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return APIResponse(status="ok", data=persona)


@router.delete("/{persona_id}", response_model=APIResponse)
async def archive_persona(
    persona_id: str,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    _require_admin("local-admin", x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    try:
        persona = _store().archive_persona(persona_id)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return APIResponse(status="ok", data=persona)


@router.post("/{persona_id}/restore", response_model=APIResponse)
async def restore_persona(
    persona_id: str,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    _require_admin("local-admin", x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    persona = _store().restore_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return APIResponse(status="ok", data=persona)


@router.get("/{persona_id}/versions", response_model=APIResponse)
async def list_versions(persona_id: str) -> APIResponse:
    return APIResponse(status="ok", data=_store().list_versions(persona_id))


@router.post("/{persona_id}/rollback", response_model=APIResponse)
async def rollback_persona(
    persona_id: str,
    req: RollbackRequest,
    x_admin_token: Optional[str] = Header(default=None),
    x_admin_user: Optional[str] = Header(default=None),
) -> APIResponse:
    if not req.admin_approved:
        return APIResponse(status="error", message="回滚人格版本必须显式 admin_approved=true")
    reviewer = _require_admin(req.reviewer, x_admin_token=x_admin_token, x_admin_user=x_admin_user)
    persona = _store().rollback(persona_id, req.version, reviewer=reviewer, note=req.note)
    if not persona:
        raise HTTPException(status_code=404, detail="persona/version not found")
    return APIResponse(status="ok", data=persona)


@router.post("/{persona_id}/proposals", response_model=APIResponse)
async def create_proposal(persona_id: str, req: ProposalCreateRequest) -> APIResponse:
    persona = _store().get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    try:
        text, patch, summary = await _generate_patch(persona, req)
        proposal = _store().create_proposal(
            persona_id=persona_id,
            source=req.source,
            session_id=req.session_id,
            message_id=req.message_id,
            reflection_id=req.reflection_id,
            proposal_text=text,
            proposed_patch=patch,
            summary=summary,
        )
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    return APIResponse(status="ok", message="人格迭代建议已生成，等待管理员审核；不会自动覆盖正文。", data=proposal)
