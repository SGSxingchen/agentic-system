"""Evolution routes for runtime Agent/Tool extension.

The project treats every Agent as a capability. These endpoints make that
capability graph explicit and allow safe dynamic tools to be added at runtime.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from core.capability import (
    DynamicToolCapability,
    apply_prompt_override,
    apply_prompt_overrides,
    load_dynamic_capabilities,
    unwrap_capability,
)
from core.config import load_single_yaml, save_yaml_config

from ..dependencies import (
    get_agent_registry,
    get_capability_registry,
    reload_agent_fn,
)
from ..schemas import APIResponse, DynamicToolCreateRequest, ToolPromptUpdateRequest

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


def _clear_cache() -> None:
    from ..main import clear_yaml_cache

    clear_yaml_cache()


def _load_capabilities_config() -> Dict[str, Any]:
    data = load_single_yaml("capabilities.yaml")
    if not isinstance(data.get("capabilities"), list):
        data["capabilities"] = []
    return data


def _capability_config_map() -> Dict[str, Dict[str, Any]]:
    data = _load_capabilities_config()
    result: Dict[str, Dict[str, Any]] = {}
    for item in data.get("capabilities", []):
        if isinstance(item, dict) and item.get("name"):
            result[str(item["name"])] = item
    return result


def _format_capability_node(name: str, agent_names: set[str]) -> Dict[str, Any]:
    cap_registry = get_capability_registry()
    capability = cap_registry.get(name) if cap_registry else None
    schema = capability.get_schema() if capability else None
    base_capability = unwrap_capability(capability) if capability else None
    is_dynamic = isinstance(base_capability, DynamicToolCapability)

    return {
        "id": name,
        "label": name,
        "type": "agent" if name in agent_names else "dynamic_tool" if is_dynamic else "tool",
        "description": schema.description if schema else "",
        "parameters": schema.parameters if schema else {},
        "mode": base_capability.mode if is_dynamic and base_capability else None,
    }


@router.get("/graph", response_model=APIResponse)
async def get_evolution_graph() -> APIResponse:
    """Return the current Agent-Tool capability graph."""

    registry = get_agent_registry()
    cap_registry = get_capability_registry()

    agent_metas = registry.list_all() if registry else []
    agent_names = {meta.name for meta in agent_metas}

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for meta in agent_metas:
        nodes[meta.name] = {
            "id": meta.name,
            "label": meta.name,
            "type": "agent",
            "status": meta.status.value,
            "description": meta.description,
            "capabilities": meta.capabilities,
        }
        for tool_name in meta.capabilities:
            edges.append(
                {
                    "source": meta.name,
                    "target": tool_name,
                    "kind": "delegates" if tool_name in agent_names else "uses",
                }
            )

    if cap_registry:
        for schema in cap_registry.list_all():
            if schema.name not in nodes:
                nodes[schema.name] = _format_capability_node(schema.name, agent_names)

    dynamic_tool_count = sum(1 for node in nodes.values() if node["type"] == "dynamic_tool")
    tool_count = sum(1 for node in nodes.values() if node["type"] != "agent")

    return APIResponse(
        status="ok",
        data={
            "summary": {
                "agents": len(agent_names),
                "tools": tool_count,
                "dynamic_tools": dynamic_tool_count,
                "edges": len(edges),
                "master_agent": "assistant" if "assistant" in agent_names else None,
            },
            "nodes": list(nodes.values()),
            "edges": edges,
            "supported_dynamic_modes": sorted(DynamicToolCapability.SUPPORTED_MODES),
            "extension_points": [
                "Create an Agent in agents.yaml or through /api/agents",
                "Create a dynamic Tool through /api/evolution/dynamic-tools",
                "Attach tools or sub-agents to an Agent tools list",
            ],
        },
    )


@router.get("/tool-prompts", response_model=APIResponse)
async def list_tool_prompts() -> APIResponse:
    """List editable Tool prompts with read-only JSON schemas."""

    registry = get_agent_registry()
    cap_registry = get_capability_registry()
    if not cap_registry:
        return APIResponse(status="error", message="CapabilityRegistry 未初始化")

    agent_names = {meta.name for meta in registry.list_all()} if registry else set()
    config_map = _capability_config_map()
    tools: List[Dict[str, Any]] = []

    for schema in cap_registry.list_all():
        if schema.name in agent_names:
            continue
        config_entry = config_map.get(schema.name, {})
        capability = cap_registry.get(schema.name)
        base_capability = unwrap_capability(capability) if capability else None
        is_dynamic = isinstance(base_capability, DynamicToolCapability)

        tools.append(
            {
                "name": schema.name,
                "type": "dynamic_tool" if is_dynamic else "tool",
                "prompt": schema.description,
                "prompt_source": "custom" if config_entry.get("prompt") else "default",
                "schema": schema.parameters,
                "returns": schema.returns,
                "mode": base_capability.mode if is_dynamic and base_capability else None,
            }
        )

    tools.sort(key=lambda item: (item["type"], item["name"]))
    return APIResponse(status="ok", data=tools)


@router.put("/tool-prompts/{name}", response_model=APIResponse)
async def update_tool_prompt(name: str, req: ToolPromptUpdateRequest) -> APIResponse:
    """Update only the LLM-facing Tool prompt, never the JSON Schema."""

    prompt = req.prompt.strip()
    if not prompt:
        return APIResponse(status="error", message="prompt 不能为空")

    registry = get_agent_registry()
    cap_registry = get_capability_registry()
    if not cap_registry or name not in cap_registry:
        return APIResponse(status="error", message=f"工具 '{name}' 不存在")

    agent_names = {meta.name for meta in registry.list_all()} if registry else set()
    if name in agent_names:
        return APIResponse(status="error", message="Agent 提示词请在智能体管理中修改")

    data = _load_capabilities_config()
    capabilities = data["capabilities"]
    target = next(
        (item for item in capabilities if isinstance(item, dict) and item.get("name") == name),
        None,
    )
    if target is None:
        target = {"name": name, "type": "native"}
        capabilities.append(target)

    target["prompt"] = prompt
    data["capabilities"] = capabilities
    save_yaml_config("capabilities.yaml", data)

    apply_prompt_override(cap_registry, name, prompt)
    _clear_cache()

    reload_agents = reload_agent_fn()
    if reload_agents:
        await reload_agents()

    return APIResponse(
        status="ok",
        message=f"工具 '{name}' 提示词已更新",
        data={"name": name, "prompt": prompt},
    )


@router.post("/dynamic-tools", response_model=APIResponse)
async def create_dynamic_tool(req: DynamicToolCreateRequest) -> APIResponse:
    """Create or update a safe dynamic tool and optionally mount it to Agents."""

    if req.mode not in DynamicToolCapability.SUPPORTED_MODES:
        return APIResponse(
            status="error",
            message=(
                "不支持的动态工具模式: "
                f"{req.mode}. 可选: {', '.join(sorted(DynamicToolCapability.SUPPORTED_MODES))}"
            ),
        )

    cap_registry = get_capability_registry()
    data = _load_capabilities_config()
    capabilities = data["capabilities"]

    existing_entries = [
        item for item in capabilities if isinstance(item, dict) and item.get("name") == req.name
    ]
    existing_dynamic = any(item.get("type") == "dynamic" for item in existing_entries)

    if existing_entries and not req.overwrite:
        return APIResponse(status="error", message=f"工具 '{req.name}' 已存在")
    if cap_registry and req.name in cap_registry and not existing_dynamic:
        return APIResponse(status="error", message=f"'{req.name}' 已被原生能力或 Agent 占用")

    capability_entry: Dict[str, Any] = {
        "name": req.name,
        "type": "dynamic",
        "mode": req.mode,
        "description": req.description,
        "config": req.config,
    }
    if req.input_schema:
        capability_entry["input_schema"] = req.input_schema

    capabilities = [
        item for item in capabilities if not (isinstance(item, dict) and item.get("name") == req.name)
    ]
    capabilities.append(capability_entry)
    data["capabilities"] = capabilities
    save_yaml_config("capabilities.yaml", data)

    if cap_registry:
        loaded = load_dynamic_capabilities(cap_registry, [capability_entry])
    else:
        loaded = []

    attached_agents: List[str] = []
    missing_agents: List[str] = []
    if req.attach_to_agents:
        agents_data = load_single_yaml("agents.yaml")
        agents = agents_data.get("agents", [])
        if isinstance(agents, list):
            for agent_name in req.attach_to_agents:
                target = next(
                    (
                        item
                        for item in agents
                        if isinstance(item, dict) and item.get("name") == agent_name
                    ),
                    None,
                )
                if not target:
                    missing_agents.append(agent_name)
                    continue
                tools = target.setdefault("tools", [])
                if req.name not in tools:
                    tools.append(req.name)
                attached_agents.append(agent_name)

            agents_data["agents"] = agents
            save_yaml_config("agents.yaml", agents_data)

        _clear_cache()
        reload_agents = reload_agent_fn()
        if reload_agents:
            await reload_agents()
    else:
        _clear_cache()

    return APIResponse(
        status="ok",
        message=f"动态工具 '{req.name}' 已装载",
        data={
            "tool": capability_entry,
            "registered": loaded,
            "attached_agents": attached_agents,
            "missing_agents": missing_agents,
        },
    )


@router.post("/reload", response_model=APIResponse)
async def reload_evolution_extensions() -> APIResponse:
    """Reload dynamic tools from YAML and refresh Agent tool wiring."""

    cap_registry = get_capability_registry()
    if not cap_registry:
        return APIResponse(status="error", message="CapabilityRegistry 未初始化")

    data = _load_capabilities_config()
    loaded = load_dynamic_capabilities(cap_registry, data["capabilities"])
    prompt_overrides = apply_prompt_overrides(cap_registry, data["capabilities"])
    _clear_cache()

    reload_agents = reload_agent_fn()
    if reload_agents:
        await reload_agents()

    return APIResponse(
        status="ok",
        message="动态能力已重新装载",
        data={"loaded_dynamic_tools": loaded, "prompt_overrides": prompt_overrides},
    )
