"""Persona CRUD and binding management tools with explicit admin guardrails."""

from __future__ import annotations

import os
from typing import Any, Dict

from core.capability.base import CapabilityBase, CapabilitySchema
from core.persona import BASE_PERSONA_ID, PersonaBindingService, PersonaStore
from core.prompts import get_tool_description


READ_DEFINITION_OPS = {"list", "get"}
MUTATE_DEFINITION_OPS = {"create", "update", "archive", "restore", "delete"}
READ_BINDING_OPS = {"list", "resolve"}
MUTATE_BINDING_OPS = {"bind_agent", "unbind_agent", "bind_session", "unbind_session"}


def _admin_decision(kwargs: Dict[str, Any], *, action: str) -> Dict[str, Any]:
    """Require an explicit local-admin decision for tool-driven mutations."""

    if not bool(kwargs.get("admin_approved")):
        return {
            "decision": "deny",
            "reason": f"admin_approved=true is required before {action}",
        }
    reviewer = str(kwargs.get("reviewer") or "").strip()
    if not reviewer:
        return {"decision": "deny", "reason": "reviewer is required"}
    expected = os.getenv("PERSONA_ADMIN_TOKEN", "").strip()
    if expected and str(kwargs.get("admin_token") or "") != expected:
        return {"decision": "deny", "reason": "valid admin_token is required"}
    return {"decision": "allow"}


class ManagePersonaDefinitionCapability(CapabilityBase):
    """List/create/update/archive/restore persona definitions."""

    @property
    def name(self) -> str:
        return "manage_persona_definition"

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
                    "operation": {
                        "type": "string",
                        "enum": sorted(READ_DEFINITION_OPS | MUTATE_DEFINITION_OPS),
                        "description": "操作: list|get|create|update|archive|restore|delete。delete 等价于安全归档。",
                    },
                    "persona_id": {
                        "type": "string",
                        "description": "get/update/archive/restore/delete 的目标人格 id。",
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "list 时是否包含 archived 人格。",
                        "default": False,
                    },
                    "payload": {
                        "type": "object",
                        "description": "create/update 使用的人格字段；允许 name/description/persona_prompt/style_rules/behavior_rules/permission_boundary/status。",
                    },
                    "reviewer": {"type": "string", "description": "执行写操作的管理员/审核人。"},
                    "admin_approved": {"type": "boolean", "description": "写操作必须显式为 true。", "default": False},
                    "admin_token": {"type": "string", "description": "若配置 PERSONA_ADMIN_TOKEN，必须提供匹配 token。"},
                },
                "required": ["operation"],
            },
            returns="人格定义、列表或写入结果；写操作会返回 audit 字段。",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=12000,
        )

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        operation = str(kwargs.get("operation") or "").strip()
        if operation in READ_DEFINITION_OPS:
            return {"decision": "allow"}
        if operation in MUTATE_DEFINITION_OPS:
            return _admin_decision(kwargs, action=f"persona definition {operation}")
        return {"decision": "deny", "reason": f"unsupported operation: {operation}"}

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        permit = self.check_permissions(**kwargs)
        if permit.get("decision") != "allow":
            return {"error": permit.get("reason"), "permission_denied": True}

        operation = str(kwargs.get("operation") or "").strip()
        persona_id = str(kwargs.get("persona_id") or "").strip()
        payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        store = PersonaStore()

        try:
            if operation == "list":
                return {
                    "success": True,
                    "personas": store.list_personas(include_archived=bool(kwargs.get("include_archived", False))),
                    "base_persona_id": BASE_PERSONA_ID,
                }
            if operation == "get":
                if not persona_id:
                    return {"error": "persona_id is required"}
                persona = store.get_persona(persona_id)
                return {"success": bool(persona), "persona": persona} if persona else {"error": "persona not found"}
            if operation == "create":
                persona = store.create_persona(payload)
            elif operation == "update":
                if not persona_id:
                    return {"error": "persona_id is required"}
                persona = store.update_persona(persona_id, payload)
                if not persona:
                    return {"error": "persona not found"}
            elif operation in {"archive", "delete"}:
                if not persona_id:
                    return {"error": "persona_id is required"}
                persona = store.archive_persona(persona_id)
                if not persona:
                    return {"error": "persona not found"}
            elif operation == "restore":
                if not persona_id:
                    return {"error": "persona_id is required"}
                persona = store.restore_persona(persona_id)
                if not persona:
                    return {"error": "persona not found"}
            else:
                return {"error": f"unsupported operation: {operation}"}
        except ValueError as exc:
            return {"error": str(exc)}

        return {
            "success": True,
            "operation": operation,
            "persona": persona,
            "audit": {
                "reviewer": str(kwargs.get("reviewer") or ""),
                "admin_approved": True,
            },
        }


class ManagePersonaBindingCapability(CapabilityBase):
    """List, resolve, bind and unbind Agent/session persona routing."""

    @property
    def name(self) -> str:
        return "manage_persona_binding"

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
                    "operation": {
                        "type": "string",
                        "enum": sorted(READ_BINDING_OPS | MUTATE_BINDING_OPS),
                        "description": "操作: list|resolve|bind_agent|unbind_agent|bind_session|unbind_session。",
                    },
                    "agent_name": {"type": "string", "description": "Agent 名称。"},
                    "session_id": {"type": "string", "description": "会话 id。"},
                    "persona_id": {"type": "string", "description": "要绑定或请求指定的人格 id。"},
                    "reviewer": {"type": "string", "description": "执行写操作的管理员/审核人。"},
                    "admin_approved": {"type": "boolean", "description": "写操作必须显式为 true。", "default": False},
                    "admin_token": {"type": "string", "description": "若配置 PERSONA_ADMIN_TOKEN，必须提供匹配 token。"},
                },
                "required": ["operation"],
            },
            returns="人格绑定表、解析结果或绑定/解绑结果。",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=8000,
        )

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        operation = str(kwargs.get("operation") or "").strip()
        if operation in READ_BINDING_OPS:
            return {"decision": "allow"}
        if operation in MUTATE_BINDING_OPS:
            return _admin_decision(kwargs, action=f"persona binding {operation}")
        return {"decision": "deny", "reason": f"unsupported operation: {operation}"}

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        permit = self.check_permissions(**kwargs)
        if permit.get("decision") != "allow":
            return {"error": permit.get("reason"), "permission_denied": True}

        operation = str(kwargs.get("operation") or "").strip()
        agent_name = str(kwargs.get("agent_name") or "").strip()
        session_id = str(kwargs.get("session_id") or "").strip()
        persona_id = str(kwargs.get("persona_id") or "").strip()
        service = PersonaBindingService()

        try:
            if operation == "list":
                return {"success": True, "bindings": service.get_bindings()}
            if operation == "resolve":
                return {
                    "success": True,
                    "persona": service.resolve(
                        agent_name=agent_name or None,
                        session_id=session_id or None,
                        persona_id=persona_id or None,
                    ),
                }
            if operation == "bind_agent":
                if not agent_name or not persona_id:
                    return {"error": "agent_name and persona_id are required"}
                result = service.bind_agent(agent_name, persona_id)
            elif operation == "unbind_agent":
                if not agent_name:
                    return {"error": "agent_name is required"}
                result = service.unbind_agent(agent_name)
            elif operation == "bind_session":
                if not session_id or not persona_id:
                    return {"error": "session_id and persona_id are required"}
                result = service.bind_session(session_id, persona_id)
            elif operation == "unbind_session":
                if not session_id:
                    return {"error": "session_id is required"}
                result = service.unbind_session(session_id)
            else:
                return {"error": f"unsupported operation: {operation}"}
        except ValueError as exc:
            return {"error": str(exc)}

        return {
            "success": True,
            "operation": operation,
            "binding": result,
            "audit": {
                "reviewer": str(kwargs.get("reviewer") or ""),
                "admin_approved": True,
            },
        }
