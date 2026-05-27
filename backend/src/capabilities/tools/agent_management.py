"""Controlled Agent configuration management tools.

These tools only read and patch ``config/agents.yaml``.  They intentionally do
not create runtime tools, start MCP clients, or grant elevated permissions.
"""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.capability.base import CapabilityBase, CapabilitySchema
from core.capability.risk import AGENT_MANAGEMENT_TOOLS, HIGH_RISK_TOOLS
from core.config import load_single_yaml, save_yaml_config
from core.mcp import (
    build_mcp_capability_status,
    merge_mcp_servers_preserving_masked_env,
    sanitize_mcp_servers_for_response,
    validate_agent_mcp_servers_payload,
    validate_mcp_server_payload,
)
from core.prompts import get_tool_description
from core.workspace import default_workspace_root, project_root, resolve_project_path


logger = logging.getLogger(__name__)


ALLOWED_AGENT_FIELDS = {
    "description",
    "system_prompt",
    "tools",
    "output_format",
    "max_iterations",
    "llm",
    "skills",
    "mcp_servers",
    "default_workspace_id",
    "default_workspace_root",
}
OUTPUT_FORMATS = {"text", "json"}
MASKED_API_KEY_VALUES = {"********", "••••••••", "**********", "***", "masked", "<masked>"}


def _config_dir() -> Path | None:
    configured = os.getenv("AGENTIC_CONFIG_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


def _load_agents_yaml() -> Dict[str, Any]:
    data = load_single_yaml("agents.yaml", config_dir=_config_dir())
    if not isinstance(data.get("agents"), list):
        data["agents"] = []
    return data


def _save_agents_yaml(data: Dict[str, Any]) -> None:
    save_yaml_config("agents.yaml", data, config_dir=_config_dir())


def _find_agent(data: Dict[str, Any], agent_name: str) -> Dict[str, Any] | None:
    for agent in data.get("agents", []):
        if isinstance(agent, dict) and agent.get("name") == agent_name:
            return agent
    return None


def _mask_secret_value(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _sanitize_agent_config(agent: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(agent)
    llm = sanitized.get("llm")
    if isinstance(llm, dict):
        api_key = str(llm.pop("api_key", "") or "").strip()
        llm["api_key_set"] = bool(api_key)
    mcp_servers = sanitized.get("mcp_servers")
    if isinstance(mcp_servers, list):
        sanitized["mcp_servers"] = [
            {**server, "status": _mcp_server_config_status(server)}
            for server in sanitize_mcp_servers_for_response(mcp_servers)
        ]
        sanitized["mcp_capability_status"] = build_mcp_capability_status(agent)
    return sanitized


def _mcp_server_config_status(server: Dict[str, Any]) -> str:
    if not bool(server.get("enabled", True)):
        return "disabled"
    if validate_mcp_server_payload(server):
        return "config_error"
    return "configured_pending_runtime"


def _sanitize_patch_preview(patch: Dict[str, Any]) -> Dict[str, Any]:
    preview = deepcopy(patch)
    llm = preview.get("llm")
    if isinstance(llm, dict):
        api_key = str(llm.pop("api_key", "") or "").strip()
        llm["api_key_set"] = bool(api_key)
    if "mcp_servers" in preview:
        preview["mcp_servers"] = sanitize_mcp_servers_for_response(preview.get("mcp_servers"))
    return preview


def _admin_decision(kwargs: Dict[str, Any], *, action: str) -> Dict[str, Any]:
    if not bool(kwargs.get("admin_approved")):
        return {
            "decision": "deny",
            "reason": f"admin_approved=true is required before {action}",
        }
    reviewer = str(kwargs.get("reviewer") or "").strip()
    if not reviewer:
        return {"decision": "deny", "reason": "reviewer is required"}
    expected = os.getenv("AGENT_MANAGER_ADMIN_TOKEN", "").strip()
    if expected and str(kwargs.get("admin_token") or "") != expected:
        return {"decision": "deny", "reason": "valid admin_token is required"}
    return {"decision": "allow"}


def _is_masked_api_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text in MASKED_API_KEY_VALUES:
        return True
    return bool(text) and set(text) <= {"*", "•"}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_default_workspace_root(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    if Path(raw).expanduser().is_absolute():
        return "default_workspace_root must be a relative path under ./workspace"
    try:
        resolved = resolve_project_path(raw)
    except Exception as exc:
        return f"default_workspace_root is invalid: {exc}"
    if not _is_relative_to(resolved, default_workspace_root().resolve()):
        return "default_workspace_root must resolve under ./workspace"
    return None


def _validate_skill_paths(skills: Any) -> str | None:
    if skills is None:
        return None
    if not isinstance(skills, dict):
        return "skills must be an object or null"

    root = project_root().resolve()
    raw_paths: list[str] = []
    directories = skills.get("directories", skills.get("paths", []))
    if isinstance(directories, str):
        raw_paths.append(directories)
    elif isinstance(directories, list):
        raw_paths.extend(str(item) for item in directories if str(item).strip())

    items = skills.get("items", skills.get("list", []))
    if isinstance(items, dict):
        items = list(items.values())
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                raw_paths.append(item)
            elif isinstance(item, dict) and item.get("path"):
                raw_paths.append(str(item["path"]))

    for raw in raw_paths:
        path = Path(raw).expanduser()
        if path.is_absolute():
            return "skills paths must be relative to the project root"
        if not _is_relative_to((root / path).resolve(), root):
            return "skills paths must stay within the project root"
    return None


def _validate_patch(
    patch: Any,
    *,
    allow_high_risk_tools: bool = False,
) -> Tuple[Dict[str, Any] | None, List[str]]:
    if not isinstance(patch, dict):
        return None, ["patch must be an object"]

    errors: List[str] = []
    unknown = sorted(set(patch) - ALLOWED_AGENT_FIELDS)
    if unknown:
        errors.append(
            "patch contains unsupported fields: "
            + ", ".join(unknown)
            + "; allowed fields are: "
            + ", ".join(sorted(ALLOWED_AGENT_FIELDS))
        )

    if "description" in patch and patch["description"] is not None and not isinstance(patch["description"], str):
        errors.append("description must be a string or null")
    if "system_prompt" in patch and patch["system_prompt"] is not None and not isinstance(patch["system_prompt"], str):
        errors.append("system_prompt must be a string or null")

    if "tools" in patch and patch["tools"] is not None:
        tools = patch["tools"]
        if not isinstance(tools, list) or not all(isinstance(item, str) and item.strip() for item in tools):
            errors.append("tools must be a list of non-empty strings or null")
        else:
            high_risk = sorted(set(tools) & HIGH_RISK_TOOLS)
            if high_risk and not allow_high_risk_tools:
                errors.append(
                    "high-risk tools are denied by default: "
                    + ", ".join(high_risk)
                    + "; set allow_high_risk_tools=true to write them"
                )

    if "output_format" in patch and patch["output_format"] is not None:
        if patch["output_format"] not in OUTPUT_FORMATS:
            errors.append("output_format must be text or json")

    if "max_iterations" in patch and patch["max_iterations"] is not None:
        value = patch["max_iterations"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 50:
            errors.append("max_iterations must be an integer between 1 and 50")

    if "llm" in patch and patch["llm"] is not None:
        llm = patch["llm"]
        if not isinstance(llm, dict):
            errors.append("llm must be an object or null")
        else:
            for key, value in llm.items():
                if key in {"provider", "api_key", "model", "base_url", "reasoning_effort"}:
                    if value is not None and not isinstance(value, str):
                        errors.append(f"llm.{key} must be a string or null")
                elif key in {"temperature", "top_p"}:
                    if value is not None and not isinstance(value, (int, float)) or isinstance(value, bool):
                        errors.append(f"llm.{key} must be a number or null")
                elif key == "max_tokens":
                    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                        errors.append("llm.max_tokens must be a positive integer or null")
                elif key == "stop_sequences":
                    if value is not None and (
                        not isinstance(value, list)
                        or not all(isinstance(item, str) for item in value)
                    ):
                        errors.append("llm.stop_sequences must be a list of strings or null")
                elif key in {"openai", "anthropic"}:
                    if value is not None and not isinstance(value, dict):
                        errors.append(f"llm.{key} must be an object or null")
                else:
                    errors.append(f"llm.{key} is not supported")

    if "skills" in patch:
        skill_error = _validate_skill_paths(patch["skills"])
        if skill_error:
            errors.append(skill_error)

    if "mcp_servers" in patch and patch["mcp_servers"] is not None:
        errors.extend(validate_agent_mcp_servers_payload(patch["mcp_servers"]))

    for field in {"default_workspace_id", "default_workspace_root"}:
        if field in patch and patch[field] is not None and not isinstance(patch[field], str):
            errors.append(f"{field} must be a string or null")

    if "default_workspace_root" in patch:
        root_error = _validate_default_workspace_root(patch["default_workspace_root"])
        if root_error:
            errors.append(root_error)

    return deepcopy(patch), errors


def _validate_agent_specific_patch(agent_name: str, patch: Dict[str, Any] | None) -> List[str]:
    errors: List[str] = []
    if not patch or "tools" not in patch or patch["tools"] is None:
        return errors
    tools = patch["tools"]
    if not isinstance(tools, list):
        return errors
    management_tools = sorted(set(tools) & AGENT_MANAGEMENT_TOOLS)
    if agent_name != "agent_manager" and management_tools:
        errors.append("Agent 管理工具只能挂载到 agent_manager: " + ", ".join(management_tools))
    return errors


def _merge_llm(existing: Any, patch_llm: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if patch_llm is None:
        return None
    merged = dict(existing) if isinstance(existing, dict) else {}
    for key, value in patch_llm.items():
        if key == "api_key" and _is_masked_api_key(value):
            continue
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged or None


def _apply_patch_to_agent(agent: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    updated = deepcopy(agent)
    for field, value in patch.items():
        if field == "llm":
            merged_llm = _merge_llm(updated.get("llm"), value)
            if merged_llm is None:
                updated.pop("llm", None)
            else:
                updated["llm"] = merged_llm
            continue
        if field == "mcp_servers":
            updated["mcp_servers"] = merge_mcp_servers_preserving_masked_env(
                updated.get("mcp_servers"),
                value,
            )
            continue
        if value is None:
            updated.pop(field, None)
        else:
            updated[field] = deepcopy(value)
    return updated


async def _reload_or_rollback(data: Dict[str, Any], previous_data: Dict[str, Any]) -> Tuple[bool, str]:
    _save_agents_yaml(data)
    reload_agents = None
    try:
        reload_agent_fn = import_module("api.dependencies").reload_agent_fn
        reload_agents = reload_agent_fn()
    except Exception:
        reload_agents = None
    if not reload_agents:
        _save_agents_yaml(previous_data)
        raise RuntimeError("Agent config reload is not configured; agents.yaml was rolled back")
    try:
        await reload_agents()
    except Exception as exc:
        _save_agents_yaml(previous_data)
        try:
            await reload_agents()
        except Exception:
            pass
        raise RuntimeError(f"Agent config reload failed and agents.yaml was rolled back: {exc}") from exc
    return True, "runtime reloaded"


class ReadAgentConfigCapability(CapabilityBase):
    """Read sanitized Agent configuration from config/agents.yaml."""

    @property
    def name(self) -> str:
        return "read_agent_config"

    @property
    def description(self) -> str:
        return get_tool_description(
            self.name,
            "只读 Agent 配置工具：读取 config/agents.yaml 中的 Agent 配置并对 api_key 脱敏。",
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "可选。指定时只读取单个 Agent；为空时返回全部 Agent。",
                    },
                },
            },
            returns="脱敏后的 Agent 配置；llm.api_key 仅返回 api_key_set。",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=20000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        agent_name = str(kwargs.get("agent_name") or "").strip()
        data = _load_agents_yaml()
        agents = [agent for agent in data.get("agents", []) if isinstance(agent, dict)]
        if agent_name:
            agent = _find_agent(data, agent_name)
            if not agent:
                return {"error": f"agent '{agent_name}' not found"}
            return {"success": True, "agent": _sanitize_agent_config(agent)}
        return {
            "success": True,
            "agents": [_sanitize_agent_config(agent) for agent in agents],
            "allowed_fields": sorted(ALLOWED_AGENT_FIELDS),
            "high_risk_tools": sorted(HIGH_RISK_TOOLS),
        }


class ValidateAgentConfigPatchCapability(CapabilityBase):
    """Validate a controlled Agent config patch without writing files."""

    @property
    def name(self) -> str:
        return "validate_agent_config_patch"

    @property
    def description(self) -> str:
        return get_tool_description(
            self.name,
            "只读 Agent 配置补丁校验工具：检查字段范围、敏感值脱敏要求、高风险工具和 MCP 配置有效性。",
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "目标 Agent 名称。"},
                    "patch": {"type": "object", "description": "字段级补丁；只允许受控字段。"},
                    "allow_high_risk_tools": {
                        "type": "boolean",
                        "description": "是否允许写入 bash/write_file/create_agent_config/create_dynamic_tool_config/dispatch_agent。",
                        "default": False,
                    },
                },
                "required": ["agent_name", "patch"],
            },
            returns="校验结果、脱敏补丁预览和变更字段列表。",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=12000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        agent_name = str(kwargs.get("agent_name") or "").strip()
        patch, errors = _validate_patch(
            kwargs.get("patch"),
            allow_high_risk_tools=bool(kwargs.get("allow_high_risk_tools", False)),
        )
        data = _load_agents_yaml()
        exists = bool(agent_name and _find_agent(data, agent_name))
        if not agent_name:
            errors.append("agent_name is required")
        elif not exists:
            errors.append(f"agent '{agent_name}' not found")
        errors.extend(_validate_agent_specific_patch(agent_name, patch))
        return {
            "success": not errors,
            "valid": not errors,
            "errors": errors,
            "agent_exists": exists,
            "changed_fields": sorted((patch or {}).keys()),
            "patch_preview": _sanitize_patch_preview(patch or {}),
            "allowed_fields": sorted(ALLOWED_AGENT_FIELDS),
            "high_risk_tools": sorted(HIGH_RISK_TOOLS),
        }


class ProposeAgentConfigPatchCapability(CapabilityBase):
    """Preview a controlled Agent config patch without writing files."""

    @property
    def name(self) -> str:
        return "propose_agent_config_patch"

    @property
    def description(self) -> str:
        return get_tool_description(
            self.name,
            "只读 Agent 配置补丁提案工具：生成应用后的脱敏配置预览，不写入文件。",
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "目标 Agent 名称。"},
                    "patch": {"type": "object", "description": "字段级补丁；只允许受控字段。"},
                    "allow_high_risk_tools": {
                        "type": "boolean",
                        "description": "是否允许提案包含高风险工具。",
                        "default": False,
                    },
                    "reason": {"type": "string", "description": "可选，提案原因或审查说明。"},
                },
                "required": ["agent_name", "patch"],
            },
            returns="补丁提案、脱敏后的当前配置和应用后配置预览。",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=20000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        agent_name = str(kwargs.get("agent_name") or "").strip()
        patch, errors = _validate_patch(
            kwargs.get("patch"),
            allow_high_risk_tools=bool(kwargs.get("allow_high_risk_tools", False)),
        )
        data = _load_agents_yaml()
        agent = _find_agent(data, agent_name) if agent_name else None
        if not agent_name:
            errors.append("agent_name is required")
        elif not agent:
            errors.append(f"agent '{agent_name}' not found")
        errors.extend(_validate_agent_specific_patch(agent_name, patch))
        if errors:
            return {"success": False, "valid": False, "errors": errors}

        proposed = _apply_patch_to_agent(agent, patch or {})
        return {
            "success": True,
            "valid": True,
            "agent_name": agent_name,
            "reason": str(kwargs.get("reason") or "").strip(),
            "changed_fields": sorted((patch or {}).keys()),
            "patch_preview": _sanitize_patch_preview(patch or {}),
            "current_agent": _sanitize_agent_config(agent),
            "proposed_agent": _sanitize_agent_config(proposed),
            "requires_admin_approval": True,
            "apply_requirements": {
                "admin_approved": True,
                "reviewer": "non-empty string",
            },
        }


class ApplyAgentConfigPatchCapability(CapabilityBase):
    """Apply a controlled Agent config patch with explicit admin approval."""

    @property
    def name(self) -> str:
        return "apply_agent_config_patch"

    @property
    def description(self) -> str:
        return get_tool_description(
            self.name,
            "受控 Agent 配置补丁应用工具：仅修改 config/agents.yaml 的白名单字段，要求 admin_approved=true 和 reviewer，热重载失败会回滚。",
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "目标 Agent 名称。"},
                    "patch": {"type": "object", "description": "字段级补丁；只允许受控字段。"},
                    "allow_high_risk_tools": {
                        "type": "boolean",
                        "description": "是否允许写入 bash/write_file/create_agent_config/create_dynamic_tool_config/dispatch_agent。",
                        "default": False,
                    },
                    "admin_approved": {"type": "boolean", "description": "必须显式为 true。", "default": False},
                    "reviewer": {"type": "string", "description": "管理员/审核人标识，不能为空。"},
                    "admin_token": {
                        "type": "string",
                        "description": "如果配置 AGENT_MANAGER_ADMIN_TOKEN，则必须提供匹配 token。",
                    },
                },
                "required": ["agent_name", "patch", "admin_approved", "reviewer"],
            },
            returns="写入结果、脱敏后的 Agent 配置、审计信息和 reload 状态。",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=20000,
        )

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        return _admin_decision(kwargs, action="applying agent config patch")

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        permit = self.check_permissions(**kwargs)
        if permit.get("decision") != "allow":
            return {"error": permit.get("reason"), "permission_denied": True}

        agent_name = str(kwargs.get("agent_name") or "").strip()
        patch, errors = _validate_patch(
            kwargs.get("patch"),
            allow_high_risk_tools=bool(kwargs.get("allow_high_risk_tools", False)),
        )
        data = _load_agents_yaml()
        previous_data = deepcopy(data)
        agents: List[Dict[str, Any]] = data.get("agents", [])
        target_index = -1
        for index, agent in enumerate(agents):
            if isinstance(agent, dict) and agent.get("name") == agent_name:
                target_index = index
                break
        if not agent_name:
            errors.append("agent_name is required")
        elif target_index < 0:
            errors.append(f"agent '{agent_name}' not found")
        errors.extend(_validate_agent_specific_patch(agent_name, patch))
        if errors:
            return {"success": False, "valid": False, "errors": errors}

        updated_agent = _apply_patch_to_agent(agents[target_index], patch or {})
        agents[target_index] = updated_agent
        data["agents"] = agents

        try:
            reload_executed, reload_message = await _reload_or_rollback(data, previous_data)
        except RuntimeError as exc:
            return {
                "success": False,
                "error": str(exc),
                "rolled_back": True,
            }

        return {
            "success": True,
            "agent_name": agent_name,
            "changed_fields": sorted((patch or {}).keys()),
            "agent": _sanitize_agent_config(updated_agent),
            "reload_executed": reload_executed,
            "reload_message": reload_message,
            "audit": {
                "admin_approved": True,
                "reviewer": str(kwargs.get("reviewer") or "").strip(),
                "allow_high_risk_tools": bool(kwargs.get("allow_high_risk_tools", False)),
            },
        }


class UpdateAgentConfigCapability(CapabilityBase):
    """A10：调用即生效的 Agent 配置更新工具。

    替代旧的 ``propose_agent_config_patch`` + ``apply_agent_config_patch`` 两段
    式审批流程。审计走 structlog ``config_change`` 日志，回溯靠 git。
    """

    @property
    def name(self) -> str:
        return "update_agent_config"

    @property
    def description(self) -> str:
        return get_tool_description(
            self.name,
            "Agent 配置更新工具：直接合并 patch 到 config/agents.yaml 的目标 Agent，"
            "调用即生效，不需要 admin_approved/reviewer。修改完会触发热重载，失败会回滚。",
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "目标 Agent 名称。",
                    },
                    "patch": {
                        "type": "object",
                        "description": (
                            "字段级补丁；支持 description / system_prompt / tools / "
                            "output_format / max_iterations / llm / skills / mcp_servers / "
                            "default_workspace_id / default_workspace_root。"
                        ),
                    },
                },
                "required": ["agent_name", "patch"],
            },
            returns="写入结果、changed_fields、脱敏后的 Agent 配置和 reload 状态。",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=20000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        agent_name = str(kwargs.get("agent_name") or "").strip()
        # A10：HIGH_RISK_TOOLS 放开 — allow_high_risk_tools=True 让 _validate_patch 不再
        # 因为 bash/dispatch_agent 等工具拒绝写入；安全靠 system.yaml forbidden_tools。
        patch, errors = _validate_patch(
            kwargs.get("patch"),
            allow_high_risk_tools=True,
        )

        data = _load_agents_yaml()
        previous_data = deepcopy(data)
        agents: List[Dict[str, Any]] = data.get("agents", [])
        target_index = -1
        for index, agent in enumerate(agents):
            if isinstance(agent, dict) and agent.get("name") == agent_name:
                target_index = index
                break

        if not agent_name:
            errors.append("agent_name is required")
        elif target_index < 0:
            errors.append(f"agent '{agent_name}' not found")
        errors.extend(_validate_agent_specific_patch(agent_name, patch))
        if errors:
            return {"success": False, "valid": False, "errors": errors}

        updated_agent = _apply_patch_to_agent(agents[target_index], patch or {})
        agents[target_index] = updated_agent
        data["agents"] = agents

        try:
            reload_executed, reload_message = await _reload_or_rollback(data, previous_data)
        except RuntimeError as exc:
            return {
                "success": False,
                "error": str(exc),
                "rolled_back": True,
            }

        changed_fields = sorted((patch or {}).keys())
        logger.info(
            "config_change",
            extra={
                "action": "update_agent",
                "agent": agent_name,
                "changed_fields": changed_fields,
            },
        )

        return {
            "success": True,
            "agent_name": agent_name,
            "changed_fields": changed_fields,
            "agent": _sanitize_agent_config(updated_agent),
            "reload_executed": reload_executed,
            "reload_message": reload_message,
        }
