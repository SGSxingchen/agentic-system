"""Safe configuration writers for Agent/Tool evolution."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.capability.base import CapabilityBase, CapabilitySchema
from core.config import load_single_yaml, save_yaml_config
from core.prompts import get_tool_description


NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SUPPORTED_DYNAMIC_MODES = {"template", "checklist", "regex_extract"}


def _config_dir() -> Optional[Path]:
    configured = os.getenv("AGENTIC_CONFIG_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


def _valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name))


def _load_yaml_list(filename: str, key: str) -> Dict[str, Any]:
    data = load_single_yaml(filename, config_dir=_config_dir())
    if not isinstance(data.get(key), list):
        data[key] = []
    return data


def _save_yaml(filename: str, data: Dict[str, Any]) -> None:
    save_yaml_config(filename, data, config_dir=_config_dir())


class CreateDynamicToolConfigCapability(CapabilityBase):
    """Create or update YAML-defined dynamic tools."""

    @property
    def name(self) -> str:
        return "create_dynamic_tool_config"

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
                    "name": {
                        "type": "string",
                        "description": "Tool 名称，必须匹配 ^[A-Za-z_][A-Za-z0-9_]*$",
                    },
                    "description": {
                        "type": "string",
                        "description": "暴露给 LLM 的工具描述/提示词",
                    },
                    "mode": {
                        "type": "string",
                        "description": "动态工具模式: template | checklist | regex_extract",
                        "default": "template",
                    },
                    "input_schema": {
                        "type": "object",
                        "description": "可选工具输入 JSON Schema",
                    },
                    "config": {
                        "type": "object",
                        "description": "模式相关配置，例如 template 或 required_terms",
                    },
                    "attach_to_agents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要挂载该工具的 Agent 名称列表",
                        "default": ["assistant"],
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "是否覆盖同名动态工具",
                        "default": False,
                    },
                },
                "required": ["name", "description", "mode"],
            },
            returns="创建的 YAML 配置条目和重新装载提示",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        name = str(kwargs.get("name") or "").strip()
        description = str(kwargs.get("description") or "").strip()
        mode = str(kwargs.get("mode") or "template").strip()
        input_schema = kwargs.get("input_schema")
        config = kwargs.get("config") or {}
        attach_to_agents = kwargs.get("attach_to_agents")
        overwrite = bool(kwargs.get("overwrite", False))

        if not _valid_name(name):
            return {"error": "name must match ^[A-Za-z_][A-Za-z0-9_]*$"}
        if not description:
            return {"error": "description is required"}
        if mode not in SUPPORTED_DYNAMIC_MODES:
            return {
                "error": (
                    f"unsupported mode '{mode}', expected one of "
                    f"{', '.join(sorted(SUPPORTED_DYNAMIC_MODES))}"
                )
            }
        if input_schema is not None and not isinstance(input_schema, dict):
            return {"error": "input_schema must be an object when provided"}
        if not isinstance(config, dict):
            return {"error": "config must be an object"}

        if attach_to_agents is None:
            attach_to_agents = ["assistant"]
        if not isinstance(attach_to_agents, list) or not all(
            isinstance(item, str) and item.strip() for item in attach_to_agents
        ):
            return {"error": "attach_to_agents must be a list of agent names"}

        capabilities_data = _load_yaml_list("capabilities.yaml", "capabilities")
        capabilities: List[Dict[str, Any]] = capabilities_data["capabilities"]
        existing = [
            item
            for item in capabilities
            if isinstance(item, dict) and item.get("name") == name
        ]
        if existing and not overwrite:
            return {"error": f"tool '{name}' already exists; set overwrite=true to replace"}
        if existing and any(item.get("type") != "dynamic" for item in existing):
            return {"error": f"'{name}' is not a dynamic tool and cannot be overwritten here"}

        entry: Dict[str, Any] = {
            "name": name,
            "type": "dynamic",
            "mode": mode,
            "description": description,
            "config": config,
        }
        if input_schema:
            entry["input_schema"] = input_schema

        capabilities_data["capabilities"] = [
            item
            for item in capabilities
            if not (isinstance(item, dict) and item.get("name") == name)
        ] + [entry]
        _save_yaml("capabilities.yaml", capabilities_data)

        agents_data = _load_yaml_list("agents.yaml", "agents")
        agents: List[Dict[str, Any]] = agents_data["agents"]
        attached: List[str] = []
        missing: List[str] = []
        for agent_name in attach_to_agents:
            target = next(
                (
                    item
                    for item in agents
                    if isinstance(item, dict) and item.get("name") == agent_name
                ),
                None,
            )
            if not target:
                missing.append(agent_name)
                continue
            tools = target.setdefault("tools", [])
            if not isinstance(tools, list):
                tools = []
                target["tools"] = tools
            if name not in tools:
                tools.append(name)
            attached.append(agent_name)

        if attached or missing:
            agents_data["agents"] = agents
            _save_yaml("agents.yaml", agents_data)

        return {
            "success": True,
            "tool": entry,
            "attached_agents": attached,
            "missing_agents": missing,
            "requires_reload": True,
            "reload_hint": "Call /api/evolution/reload or restart the backend before using the new tool.",
        }


class CreateAgentConfigCapability(CapabilityBase):
    """Create or update YAML-defined Agent configs."""

    @property
    def name(self) -> str:
        return "create_agent_config"

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
                    "name": {
                        "type": "string",
                        "description": "Agent 名称，必须匹配 ^[A-Za-z_][A-Za-z0-9_]*$",
                    },
                    "description": {
                        "type": "string",
                        "description": "Agent 描述，同时作为被委派时的工具描述",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "定义 Agent 角色、流程、约束和输出契约的系统提示词",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "该 Agent 可使用的 Tool 或子 Agent 名称列表",
                        "default": [],
                    },
                    "output_format": {
                        "type": "string",
                        "description": "输出格式: text | json",
                        "default": "text",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "tool_use 循环上限",
                        "default": 10,
                    },
                    "input_schema": {
                        "type": "object",
                        "description": "该 Agent 被当作工具使用时展示的 JSON Schema",
                    },
                    "attach_to_assistant": {
                        "type": "boolean",
                        "description": "是否将该 Agent 名称加入 assistant.tools",
                        "default": True,
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "是否覆盖同名 Agent",
                        "default": False,
                    },
                },
                "required": ["name", "description", "system_prompt"],
            },
            returns="创建的 Agent 配置和重新装载提示",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        name = str(kwargs.get("name") or "").strip()
        description = str(kwargs.get("description") or "").strip()
        system_prompt = str(kwargs.get("system_prompt") or "").strip()
        tools = kwargs.get("tools") or []
        output_format = str(kwargs.get("output_format") or "text").strip()
        max_iterations = int(kwargs.get("max_iterations") or 10)
        input_schema = kwargs.get("input_schema")
        attach_to_assistant = bool(kwargs.get("attach_to_assistant", True))
        overwrite = bool(kwargs.get("overwrite", False))

        if not _valid_name(name):
            return {"error": "name must match ^[A-Za-z_][A-Za-z0-9_]*$"}
        if not description:
            return {"error": "description is required"}
        if not system_prompt:
            return {"error": "system_prompt is required"}
        if output_format not in {"text", "json"}:
            return {"error": "output_format must be text or json"}
        if not isinstance(tools, list) or not all(
            isinstance(item, str) and item.strip() for item in tools
        ):
            return {"error": "tools must be a list of tool or Agent names"}
        if input_schema is not None and not isinstance(input_schema, dict):
            return {"error": "input_schema must be an object when provided"}
        if max_iterations < 1 or max_iterations > 50:
            return {"error": "max_iterations must be between 1 and 50"}

        data = _load_yaml_list("agents.yaml", "agents")
        agents: List[Dict[str, Any]] = data["agents"]
        existing = [
            item for item in agents if isinstance(item, dict) and item.get("name") == name
        ]
        if existing and not overwrite:
            return {"error": f"agent '{name}' already exists; set overwrite=true to replace"}

        entry: Dict[str, Any] = {
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "tools": tools,
            "output_format": output_format,
            "max_iterations": max_iterations,
        }
        if input_schema:
            entry["input_schema"] = input_schema

        agents = [
            item
            for item in agents
            if not (isinstance(item, dict) and item.get("name") == name)
        ] + [entry]

        assistant_attached = False
        if attach_to_assistant and name != "assistant":
            assistant = next(
                (
                    item
                    for item in agents
                    if isinstance(item, dict) and item.get("name") == "assistant"
                ),
                None,
            )
            if assistant:
                assistant_tools = assistant.setdefault("tools", [])
                if not isinstance(assistant_tools, list):
                    assistant_tools = []
                    assistant["tools"] = assistant_tools
                if name not in assistant_tools:
                    assistant_tools.append(name)
                assistant_attached = True

        data["agents"] = agents
        _save_yaml("agents.yaml", data)

        return {
            "success": True,
            "agent": entry,
            "attached_to_assistant": assistant_attached,
            "requires_reload": True,
            "reload_hint": "Call /api/evolution/reload or restart the backend before using the new Agent.",
        }
