"""Persona evolution tools with explicit review boundaries."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from core.capability.base import CapabilityBase, CapabilitySchema
from core.persona import BASE_PERSONA_ID, PersonaStore
from core.prompts import get_tool_description


def _store() -> PersonaStore:
    return PersonaStore()


def _admin_decision(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Validate explicit confirmation for persona mutation tools."""

    if not bool(kwargs.get("admin_approved")):
        return {
            "decision": "deny",
            "reason": "admin_approved=true is required before applying a persona patch",
        }
    reviewer = str(kwargs.get("reviewer") or "").strip()
    if not reviewer:
        return {"decision": "deny", "reason": "reviewer is required"}
    expected = os.getenv("PERSONA_ADMIN_TOKEN", "").strip()
    if expected and str(kwargs.get("admin_token") or "") != expected:
        return {"decision": "deny", "reason": "valid admin_token is required"}
    return {"decision": "allow"}


class ReadPersonaDefinitionCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "read_persona_definition"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "description": "可选。指定时读取单个人格；为空时列出人格定义。",
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "列出人格时是否包含 archived。",
                        "default": False,
                    },
                },
            },
            returns="人格定义或人格定义列表",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=12000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        persona_id = str(kwargs.get("persona_id") or "").strip()
        store = _store()
        if persona_id:
            persona = store.get_persona(persona_id)
            if not persona:
                return {"error": f"persona '{persona_id}' not found"}
            return {"persona": persona}
        return {
            "personas": store.list_personas(include_archived=bool(kwargs.get("include_archived", False))),
            "base_persona_id": BASE_PERSONA_ID,
        }


class RecordPersonaFeedbackCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "record_persona_feedback"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "persona_id": {"type": "string", "description": "被观察/反馈的人格 id"},
                    "feedback": {"type": "string", "description": "反馈、观察或问题描述"},
                    "source": {
                        "type": "string",
                        "description": "feedback | observation | reflection | admin_instruction",
                        "default": "feedback",
                    },
                    "session_id": {"type": "string", "description": "可选来源会话 id"},
                    "observer": {"type": "string", "description": "记录者，默认 persona_evolution"},
                    "metadata": {"type": "object", "description": "可选结构化来源元数据"},
                },
                "required": ["persona_id", "feedback"],
            },
            returns="已记录的反馈记录；不会修改人格正文",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=6000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        try:
            record = _store().record_feedback(
                persona_id=str(kwargs.get("persona_id") or ""),
                feedback=str(kwargs.get("feedback") or ""),
                source=str(kwargs.get("source") or "feedback"),
                session_id=(str(kwargs.get("session_id")) if kwargs.get("session_id") else None),
                observer=str(kwargs.get("observer") or "persona_evolution"),
                metadata=kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else {},
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"success": True, "feedback": record}


class GeneratePersonaPatchProposalCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "generate_persona_patch_proposal"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "persona_id": {"type": "string", "description": "目标人格 id"},
                    "proposal_text": {"type": "string", "description": "建议正文，说明为什么需要改"},
                    "proposed_patch": {
                        "type": "object",
                        "description": "待审核补丁，只允许 name/description/persona_prompt/style_rules/behavior_rules/permission_boundary/status",
                    },
                    "summary": {"type": "string", "description": "短摘要"},
                    "source": {"type": "string", "description": "建议来源", "default": "persona_evolution_agent"},
                    "session_id": {"type": "string", "description": "可选来源会话 id"},
                    "message_id": {"type": "string", "description": "可选来源消息 id"},
                    "reflection_id": {"type": "string", "description": "可选反思 id"},
                },
                "required": ["persona_id", "proposal_text", "proposed_patch"],
            },
            returns="pending 状态的人格补丁建议；批准前不会生效",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=12000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        patch = kwargs.get("proposed_patch")
        if not isinstance(patch, dict) or not patch:
            return {"error": "proposed_patch must be a non-empty object"}
        try:
            proposal = _store().create_proposal(
                persona_id=str(kwargs.get("persona_id") or ""),
                source=str(kwargs.get("source") or "persona_evolution_agent"),
                proposal_text=str(kwargs.get("proposal_text") or "人格迭代建议"),
                proposed_patch=patch,
                summary=str(kwargs.get("summary") or "人格迭代智能体生成的待审核建议。"),
                session_id=str(kwargs.get("session_id")) if kwargs.get("session_id") else None,
                message_id=str(kwargs.get("message_id")) if kwargs.get("message_id") else None,
                reflection_id=str(kwargs.get("reflection_id")) if kwargs.get("reflection_id") else None,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"success": True, "proposal": proposal, "requires_admin_approval": True}


class ApplyConfirmedPersonaPatchCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "apply_confirmed_persona_patch"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "pending 补丁建议 id"},
                    "admin_approved": {"type": "boolean", "description": "必须显式为 true"},
                    "reviewer": {"type": "string", "description": "批准人/管理员标识"},
                    "note": {"type": "string", "description": "可选审批备注"},
                    "admin_token": {"type": "string", "description": "如 PERSONA_ADMIN_TOKEN 已配置则必填"},
                },
                "required": ["proposal_id", "admin_approved", "reviewer"],
            },
            returns="批准结果和新人格版本；未确认时返回 permission_denied",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=12000,
        )

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        return _admin_decision(kwargs)

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        permit = _admin_decision(kwargs)
        if permit.get("decision") != "allow":
            return {"error": permit.get("reason"), "permission_denied": True}
        proposal_id = str(kwargs.get("proposal_id") or "").strip()
        if not proposal_id:
            return {"error": "proposal_id is required"}
        try:
            result = _store().approve_proposal(
                proposal_id,
                reviewer=str(kwargs.get("reviewer") or "local-admin"),
                note=str(kwargs.get("note") or ""),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        if not result:
            return {"error": f"proposal '{proposal_id}' not found"}
        return {"success": True, **result}


class ListPersonaPatchHistoryCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "list_persona_patch_history"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "persona_id": {"type": "string", "description": "可选人格 id"},
                    "status": {"type": "string", "description": "可选 proposal 状态 pending/approved/rejected"},
                    "limit": {"type": "integer", "description": "反馈记录返回上限", "default": 20},
                    "include_versions": {"type": "boolean", "description": "是否返回版本历史", "default": True},
                    "include_feedback": {"type": "boolean", "description": "是否返回反馈记录", "default": True},
                },
            },
            returns="补丁建议、版本历史和反馈记录",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=16000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        persona_id = str(kwargs.get("persona_id") or "").strip() or None
        store = _store()
        status = str(kwargs.get("status") or "").strip() or None
        limit = int(kwargs.get("limit") or 20)
        data: Dict[str, Any] = {
            "proposals": store.list_proposals(status=status, persona_id=persona_id),
        }
        if bool(kwargs.get("include_versions", True)):
            data["versions"] = store.list_versions(persona_id) if persona_id else {}
        if bool(kwargs.get("include_feedback", True)):
            data["feedback"] = store.list_feedback(persona_id=persona_id, limit=limit)
        return data
