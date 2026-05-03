"""Evolution routes for runtime Agent/Tool extension.

The project treats every Agent as a capability. These endpoints make that
capability graph explicit and allow safe dynamic tools to be added at runtime.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
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
    get_memory_buffer,
    get_memory_formation,
    get_memory_store,
    get_pipeline,
    get_bus,
    reload_agent_fn,
)
from ..schemas import (
    APIResponse,
    DynamicToolCreateRequest,
    EvolutionCommandRequest,
    ToolPromptUpdateRequest,
)

router = APIRouter(prefix="/api/evolution", tags=["evolution"])

PROJECT_ROOT = Path(__file__).resolve().parents[4]


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


def _safe_status(ok: bool, *, empty: bool = False, disabled: bool = False) -> str:
    if disabled:
        return "disabled"
    if empty:
        return "empty"
    return "healthy" if ok else "warning"


def _truncate(value: str, limit: int = 140) -> str:
    value = str(value or "").strip().replace("\n", " ")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _build_evolution_graph_payload() -> Dict[str, Any]:
    """Build the current Agent/Tool capability graph from live registries."""

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

    return {
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
            "Evolve by changing architecture deliberately, not by treating Agent/Tool CRUD as evolution itself",
            "Create or update Agents in config/agents.yaml or through /api/agents when a new role is justified",
            "Create deterministic dynamic Tools through /api/evolution/dynamic-tools only for safe template/checklist/regex_extract behavior",
            "Use Pipeline/Task execution to validate architecture changes with tests and review",
        ],
    }


def _configured_agents() -> List[Dict[str, Any]]:
    agents = load_single_yaml("agents.yaml").get("agents", [])
    return agents if isinstance(agents, list) else []


def _configured_pipelines() -> Dict[str, Any]:
    data = load_single_yaml("pipelines.yaml")
    pipelines = data.get("pipelines")
    if isinstance(pipelines, dict):
        return pipelines
    return data if isinstance(data, dict) else {}


def _skill_items() -> List[Dict[str, Any]]:
    registry = get_agent_registry()
    runtime_agents = {meta.name: registry.get(meta.name) for meta in registry.list_all()} if registry else {}
    items: List[Dict[str, Any]] = []
    for agent_def in _configured_agents():
        if not isinstance(agent_def, dict):
            continue
        name = str(agent_def.get("name") or "")
        skills = agent_def.get("skills") if isinstance(agent_def.get("skills"), dict) else {}
        runtime = getattr(runtime_agents.get(name), "_runtime_config", {}) if runtime_agents.get(name) else {}
        loaded_skills = runtime.get("skills", []) if isinstance(runtime, dict) else []
        enabled = bool(skills.get("enabled", True)) if skills else False
        directories = skills.get("directories", []) if isinstance(skills.get("directories"), list) else []
        inline_items = skills.get("items", []) if isinstance(skills.get("items"), list) else []
        disabled = skills.get("disabled", []) if isinstance(skills.get("disabled"), list) else []
        items.append(
            {
                "agent": name,
                "enabled": enabled,
                "configured": bool(skills),
                "configured_items": len(inline_items),
                "directories": directories,
                "disabled": disabled,
                "strategy": skills.get("strategy", "metadata_and_instructions") if skills else "",
                "loaded_count": len(loaded_skills) if isinstance(loaded_skills, list) else 0,
            }
        )
    return items


def _mcp_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for agent_def in _configured_agents():
        if not isinstance(agent_def, dict):
            continue
        servers = agent_def.get("mcp_servers", [])
        if not isinstance(servers, list):
            servers = []
        enabled = [server for server in servers if isinstance(server, dict) and server.get("enabled", True)]
        if servers:
            items.append(
                {
                    "agent": agent_def.get("name", ""),
                    "servers": len(servers),
                    "enabled": len(enabled),
                    "status": "configured_not_connected",
                }
            )
    return items


async def _memory_component(config: Dict[str, Any]) -> Dict[str, Any]:
    store = get_memory_store()
    formation = get_memory_formation()
    buffer = get_memory_buffer()
    memory_config = config.get("memory", {}) if isinstance(config.get("memory"), dict) else {}
    counts = {"episodic": 0, "semantic": 0, "procedural": 0}
    total = 0
    if store:
        try:
            from core.memory import MemoryType

            total = await store.count()
            for memory_type in MemoryType:
                counts[memory_type.value] = await store.count(memory_type)
        except Exception:
            total = 0
    auto_reflection = bool(memory_config.get("auto_reflection_enabled", True))
    return {
        "id": "memory",
        "title": "Memory / Reflection",
        "status": _safe_status(store is not None, disabled=not auto_reflection and not store),
        "summary": (
            f"{type(store).__name__ if store else 'No MemoryStore'}；"
            f"auto reflection {'enabled' if auto_reflection else 'disabled'}"
        ),
        "metrics": {
            "total": total,
            **counts,
            "reflection_min_turns": getattr(buffer, "min_turns", memory_config.get("reflection_min_turns", 3)) if buffer else memory_config.get("reflection_min_turns", 3),
        },
        "items": [
            {"label": "backend", "value": memory_config.get("backend", "chroma")},
            {"label": "runtime_store", "value": type(store).__name__ if store else "not initialized"},
            {"label": "persist_dir", "value": memory_config.get("persist_dir", "./data/chroma")},
            {"label": "consolidation", "value": getattr(formation, "consolidation_threshold", memory_config.get("consolidation_threshold", 0.3)) if formation else memory_config.get("consolidation_threshold", 0.3)},
        ],
        "empty_state": "长期记忆未初始化；系统仍可对话，但无法形成/召回长期状态。",
    }


def _agent_component(graph: Dict[str, Any]) -> Dict[str, Any]:
    agent_nodes = [node for node in graph["nodes"] if node.get("type") == "agent"]
    return {
        "id": "agents",
        "title": "Assistants / Agents",
        "status": _safe_status(bool(agent_nodes), empty=not bool(agent_nodes)),
        "summary": "assistant 是协作入口之一；planner/coder/reviewer/creator 等 Agent 共同构成运行时。",
        "metrics": {
            "total": len(agent_nodes),
            "idle": sum(1 for node in agent_nodes if node.get("status") == "idle"),
            "edges": graph["summary"].get("edges", 0),
        },
        "items": [
            {
                "name": node.get("id"),
                "status": node.get("status", "unknown"),
                "description": _truncate(node.get("description", "")),
                "capability_count": len(node.get("capabilities") or []),
            }
            for node in sorted(agent_nodes, key=lambda item: item.get("id", ""))
        ],
        "empty_state": "尚未注册 Agent；请检查 config/agents.yaml 或后端初始化日志。",
    }


def _tool_component(graph: Dict[str, Any]) -> Dict[str, Any]:
    tool_nodes = [node for node in graph["nodes"] if node.get("type") != "agent"]
    dynamic = [node for node in tool_nodes if node.get("type") == "dynamic_tool"]
    return {
        "id": "tools",
        "title": "Tools / Capabilities",
        "status": _safe_status(bool(tool_nodes), empty=not bool(tool_nodes)),
        "summary": "Tools 是 Agent 可调用的受限能力；它们是系统组件，不等同于系统进化。",
        "metrics": {"total": len(tool_nodes), "dynamic": len(dynamic), "native": len(tool_nodes) - len(dynamic)},
        "items": [
            {
                "name": node.get("id"),
                "type": node.get("type"),
                "mode": node.get("mode"),
                "description": _truncate(node.get("description", "")),
            }
            for node in sorted(tool_nodes, key=lambda item: (item.get("type", ""), item.get("id", "")))[:24]
        ],
        "empty_state": "尚未发现 Tool；Agent 只能做纯 LLM 推理。",
    }


def _runtime_component() -> Dict[str, Any]:
    bus = get_bus()
    pipeline = get_pipeline()
    bus_stats = bus.get_stats() if bus else {}
    runtime_templates = pipeline.list_templates() if pipeline else {}
    if not runtime_templates:
        runtime_templates = _configured_pipelines()
    template_items = []
    for name, template in runtime_templates.items():
        if isinstance(template, dict):
            template_items.append(
                {
                    "name": name,
                    "mode": template.get("mode", "sequential"),
                    "description": _truncate(template.get("description", "")),
                    "steps": len(template.get("steps", [])) if isinstance(template.get("steps"), list) else 0,
                }
            )
    return {
        "id": "runtime",
        "title": "Runtime / Orchestration",
        "status": _safe_status(bool(bus_stats.get("running")) and pipeline is not None, empty=not bool(template_items)),
        "summary": "UnifiedBus + Pipeline 将 Agent 与 Tool 组织为可观测的执行流。",
        "metrics": {
            "bus_running": bool(bus_stats.get("running")),
            "queue_size": bus_stats.get("queue_size", 0),
            "history_size": bus_stats.get("history_size", 0),
            "templates": len(template_items),
        },
        "items": template_items,
        "empty_state": "暂无 Pipeline 模板；仍可直接调用 Agent，但缺少自动化编排。",
    }


def _model_component(config: Dict[str, Any]) -> Dict[str, Any]:
    llm = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
    return {
        "id": "models",
        "title": "Models / Providers",
        "status": _safe_status(bool(llm.get("model"))),
        "summary": f"{llm.get('provider', 'openai')} / {llm.get('model') or 'model not configured'}",
        "metrics": {
            "api_key_set": bool(llm.get("api_key")),
            "max_tokens": llm.get("max_tokens", 4096),
            "temperature": llm.get("temperature", 0.7),
        },
        "items": [
            {"label": "provider", "value": llm.get("provider", "openai")},
            {"label": "model", "value": llm.get("model", "") or "not configured"},
            {"label": "base_url", "value": llm.get("base_url", "") or "SDK default"},
            {"label": "api_key", "value": "configured" if llm.get("api_key") else "missing"},
        ],
        "empty_state": "模型未配置；请到设置页配置 provider/model/api key。",
    }


def _skills_component() -> Dict[str, Any]:
    skills = _skill_items()
    configured = [item for item in skills if item.get("configured")]
    loaded_total = sum(int(item.get("loaded_count") or 0) for item in skills)
    return {
        "id": "skills",
        "title": "Skills / MCP Context",
        "status": _safe_status(True, empty=not bool(configured)),
        "summary": "Skills/MCP server 配置按 Agent 作用域注入，只提供上下文，不自动扩大权限。",
        "metrics": {
            "agents_with_skills": len(configured),
            "loaded_skills": loaded_total,
            "mcp_bindings": len(_mcp_items()),
        },
        "items": configured if configured else [],
        "empty_state": "当前没有 Agent-scoped Skill；系统仍可通过 Tool 与 Agent 协作。",
    }


def _evolution_pipeline_component(graph: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    memory_config = config.get("memory", {}) if isinstance(config.get("memory"), dict) else {}
    return {
        "id": "evolution_pipeline",
        "title": "Evolution / Reflection Pipeline",
        "status": "healthy",
        "summary": "进化闭环 = 观测当前架构 → 描述目标 → 生成任务 → 修改配置/代码 → 测试验证 → 反思沉淀。",
        "metrics": {
            "dynamic_modes": len(graph.get("supported_dynamic_modes", [])),
            "extension_points": len(graph.get("extension_points", [])),
            "auto_reflection": bool(memory_config.get("auto_reflection_enabled", True)),
        },
        "items": [
            {"label": "command_entry", "value": "Evolution Command"},
            {"label": "safe_dynamic_modes", "value": ", ".join(graph.get("supported_dynamic_modes", []))},
            {"label": "reflection_window", "value": memory_config.get("reflection_max_messages", 12)},
        ],
        "empty_state": "进化入口可用；请输入目标生成可执行任务指令。",
    }


def _observability_component(config: Dict[str, Any]) -> Dict[str, Any]:
    bus = get_bus()
    bus_stats = bus.get_stats() if bus else {}
    config_files = []
    for filename in ("system.yaml", "agents.yaml", "capabilities.yaml", "pipelines.yaml"):
        path = PROJECT_ROOT / "config" / filename
        config_files.append({"name": filename, "exists": path.exists()})
    task_counts: Dict[str, int] = {}
    try:
        from .tasks import get_task_registry

        for task in get_task_registry().list():
            status = getattr(task.status, "value", str(task.status))
            task_counts[status] = task_counts.get(status, 0) + 1
    except Exception:
        task_counts = {}
    return {
        "id": "observability",
        "title": "Observability / Config",
        "status": _safe_status(bool(bus_stats.get("running"))),
        "summary": "配置文件、Bus 指标和 Task 状态用于判断系统是否可安全进化。",
        "metrics": {
            "messages_published": bus_stats.get("messages_published", 0),
            "messages_delivered": bus_stats.get("messages_delivered", 0),
            "event_types": len(bus_stats.get("event_types", []) or []),
            "tasks": sum(task_counts.values()),
        },
        "items": [
            {"label": "config_files", "value": config_files},
            {"label": "task_status", "value": task_counts},
            {"label": "system_version", "value": (config.get("system", {}) or {}).get("version", "unknown") if isinstance(config.get("system"), dict) else "unknown"},
        ],
        "empty_state": "Bus 未运行；监控指标不可用。",
    }


async def _build_system_status_payload() -> Dict[str, Any]:
    from core.config import load_config

    config = load_config()
    graph = _build_evolution_graph_payload()
    system_config = config.get("system", {}) if isinstance(config.get("system"), dict) else {}
    components = [
        _agent_component(graph),
        _tool_component(graph),
        _skills_component(),
        await _memory_component(config),
        _model_component(config),
        _runtime_component(),
        _evolution_pipeline_component(graph, config),
        _observability_component(config),
    ]
    warning_count = sum(1 for component in components if component.get("status") in {"warning", "empty"})
    overview = {
        "system_name": system_config.get("name", "Multi-Agent Code System"),
        "version": system_config.get("version", "unknown"),
        "generated_at": datetime.now().isoformat(),
        "readiness": "attention_needed" if warning_count else "ready",
        "architecture": "Agentic runtime with Agents, Tools, Memory, Skills, Models, Pipeline orchestration and Observability",
        "agent_count": graph["summary"].get("agents", 0),
        "tool_count": graph["summary"].get("tools", 0),
        "dynamic_tool_count": graph["summary"].get("dynamic_tools", 0),
        "pipeline_count": _runtime_component()["metrics"].get("templates", 0),
        "model": _model_component(config)["summary"],
    }
    return {
        "overview": overview,
        "components": components,
        "graph": graph,
    }


def _component_snapshot(status_payload: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for component in status_payload.get("components", []):
        metrics = component.get("metrics", {})
        metric_text = ", ".join(f"{key}={value}" for key, value in metrics.items() if not isinstance(value, (dict, list)))
        lines.append(f"- {component.get('title')}: status={component.get('status')}; {metric_text}")
    return lines


def _target_components(goal: str) -> List[str]:
    normalized = goal.lower()
    mapping = [
        ("memory", ["记忆", "memory", "recall", "reflection", "反思"]),
        ("agents", ["agent", "assistant", "planner", "coder", "reviewer", "智能体"]),
        ("tools", ["tool", "capability", "工具", "能力"]),
        ("runtime", ["pipeline", "workflow", "orchestration", "管线", "编排"]),
        ("models", ["model", "provider", "llm", "模型"]),
        ("observability", ["monitor", "observability", "config", "监控", "配置"]),
        ("skills", ["skill", "mcp", "技能"]),
    ]
    targets = [name for name, terms in mapping if any(term in normalized or term in goal for term in terms)]
    return targets or ["architecture", "runtime", "tests"]


def _build_command_text(goal: str, status_payload: Dict[str, Any]) -> str:
    overview = status_payload.get("overview", {})
    targets = _target_components(goal)
    snapshot = "\n".join(_component_snapshot(status_payload))
    return (
        "请作为 Agentic System Evolution 任务执行，而不是进行单纯 Agent/Tool CRUD。\n\n"
        f"目标：{goal.strip()}\n\n"
        "当前系统架构快照：\n"
        f"- system={overview.get('system_name')} version={overview.get('version')} readiness={overview.get('readiness')}\n"
        f"- model={overview.get('model')} agents={overview.get('agent_count')} tools={overview.get('tool_count')} dynamic_tools={overview.get('dynamic_tool_count')} pipelines={overview.get('pipeline_count')}\n"
        f"{snapshot}\n\n"
        "请按以下进化流程工作：\n"
        "1. 先审查现状：确认目标涉及的系统组件、已有配置/API/页面和测试，不要假设 assistant 等于整个系统。\n"
        f"2. 重点评估组件：{', '.join(targets)}。说明为什么需要改变这些组件，以及哪些组件不应改。\n"
        "3. 设计最小可行进化方案：包含架构影响、数据流、权限/安全边界、fallback/empty state、兼容性策略。\n"
        "4. 按项目规范先更新相关文档，再实现代码；优先复用现有 manager/service/registry 状态，不硬编码假数据。\n"
        "5. 实现后运行必要验证：前端 build/typecheck，后端 pytest 或 compileall；记录失败与修复。\n"
        "6. 输出变更摘要、涉及文件、测试结果和后续可选演进。\n\n"
        "验收标准：用户能从系统层面理解这次进化；Agent、Tool、Memory、Model、Pipeline、Observability 的边界保持清晰；没有破损状态或伪造运行数据。"
    )


@router.get("/graph", response_model=APIResponse)
async def get_evolution_graph() -> APIResponse:
    """Return the current Agent-Tool capability graph."""

    return APIResponse(status="ok", data=_build_evolution_graph_payload())


@router.get("/system-status", response_model=APIResponse)
async def get_system_status() -> APIResponse:
    """Return an Agentic System architecture/status summary for the evolution UI."""

    return APIResponse(status="ok", data=await _build_system_status_payload())


@router.post("/command", response_model=APIResponse)
async def create_evolution_command(req: EvolutionCommandRequest) -> APIResponse:
    """Generate a concrete evolution instruction from a goal and live system status."""

    goal = req.goal.strip()
    if not goal:
        return APIResponse(status="error", message="goal 不能为空")
    status_payload = await _build_system_status_payload()
    command = _build_command_text(goal, status_payload)
    return APIResponse(
        status="ok",
        data={
            "goal": goal,
            "target_components": _target_components(goal),
            "command": command,
            "status_snapshot": status_payload.get("overview", {}),
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
