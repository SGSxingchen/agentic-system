"""A10: update_persona — 调用即生效的 persona 配置更新工具。

Plan Task 10。替代 propose+approve+aply persona 三段式流程：直接接
``persona_id + patch`` 写盘并自动发版本；审计走 structlog
``config_change`` 日志，回溯靠 git。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from core.capability.base import CapabilityBase, CapabilitySchema
from core.persona import PersonaStore
from core.prompts import get_tool_description


logger = logging.getLogger(__name__)


def _store() -> PersonaStore:
    return PersonaStore()


class UpdatePersonaCapability(CapabilityBase):
    """A10：调用即生效的 Persona 配置更新工具。"""

    @property
    def name(self) -> str:
        return "update_persona"

    @property
    def description(self) -> str:
        return get_tool_description(
            self.name,
            "Persona 配置更新工具：合并 patch 到指定人格，调用即生效，自动发版本。"
            "审计走 config_change 日志，回溯靠 git。",
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "description": "目标 persona id。",
                    },
                    "patch": {
                        "type": "object",
                        "description": (
                            "字段级补丁；支持 name / description / persona_prompt / "
                            "style_rules / behavior_rules / permission_boundary / status。"
                        ),
                    },
                },
                "required": ["persona_id", "patch"],
            },
            returns="更新后的 persona 配置和 changed_fields。",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=12000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        persona_id = str(kwargs.get("persona_id") or "").strip()
        patch = kwargs.get("patch")

        if not persona_id:
            return {"success": False, "error": "persona_id is required"}
        if not isinstance(patch, dict) or not patch:
            return {"success": False, "error": "patch must be a non-empty object"}

        store = _store()
        try:
            persona = store.update_persona(persona_id, patch)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        if not persona:
            return {"success": False, "error": f"persona '{persona_id}' not found"}

        changed_fields = sorted(patch.keys())
        logger.info(
            "config_change",
            extra={
                "action": "update_persona",
                "persona_id": persona_id,
                "changed_fields": changed_fields,
            },
        )

        return {
            "success": True,
            "persona": persona,
            "changed_fields": changed_fields,
        }
