"""智能体管理路由

端点:
- GET  /api/agents              — 列出所有已注册 Agent
- GET  /api/agents/configs      — 列出 Agent 配置视图（Tools/MCP/Skills/默认工作区）
- GET  /api/agents/{name}/config — 获取单个 Agent 配置视图
- GET  /api/agents/{name}       — 获取特定 Agent 详情
- POST /api/agents              — 创建新 Agent
- PUT  /api/agents/{name}       — 更新 Agent 配置
- POST /api/agents/{name}/mcp/import — 导入常见 MCP 配置
- DELETE /api/agents/{name}     — 删除 Agent
- POST /api/agents/{name}/invoke — 直接调用某个 Agent
- GET  /api/agents/capabilities/list — 列出所有可用能力（供 Agent 选择 tools）
"""
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..schemas import (
    APIResponse,
    AgentInfo,
    AgentMCPImportRequest,
    AgentMCPMount,
    AgentInvokeRequest,
    AgentCreateRequest,
    AgentSkillMount,
    AgentToolMount,
    AgentUpdateRequest,
    AgentWorkspaceBinding,
)
from ..dependencies import get_agent_registry, get_capability_registry, reload_agent_fn
from core.capability.risk import AGENT_MANAGEMENT_TOOLS, HIGH_RISK_TOOLS
from core.chat_history import ChatHistoryStore
from core.config import load_single_yaml, save_yaml_config
from core.persona import BASE_PERSONA_ID, DEFAULT_BINDABLE_AGENT_ROLES, PersonaBindingService
from core.workspace import (
    WorkspaceNotFoundError,
    WorkspaceStore,
    default_workspace_root,
    project_root,
    resolve_project_path,
    session_workspace_id,
    session_workspace_root,
)
from core.mcp import (
    build_mcp_capability_status,
    merge_mcp_servers_preserving_masked_env,
    sanitize_mcp_servers_for_response,
    validate_agent_mcp_servers_payload,
    validate_mcp_server_payload,
)
from core.mcp_import import merge_imported_mcp_servers, parse_mcp_import_text
from ..websocket.handlers import build_memory_context, schedule_memory_reflection

router = APIRouter(prefix="/api/agents", tags=["agents"])

PROTECTED_AGENT_NAMES = {
    *DEFAULT_BINDABLE_AGENT_ROLES,
    "agent_manager",
    "persona_evolution",
}
MASKED_SECRET_VALUES = {"********", "••••••••"}


class AgentPersonaBindRequest(BaseModel):
    persona_id: str = Field(default=BASE_PERSONA_ID)


def _known_agent_roles() -> list[str]:
    roles = list(DEFAULT_BINDABLE_AGENT_ROLES)
    for name in _agent_config_map().keys():
        if name and name not in roles:
            roles.append(name)
    return roles


# ─── 辅助函数 ─────────────────────────────────────────────


def _clear_cache():
    from ..main import clear_yaml_cache
    clear_yaml_cache()


def _agent_config_map():
    data = load_single_yaml("agents.yaml")
    agents = data.get("agents", [])
    if not isinstance(agents, list):
        return {}
    return {
        item.get("name"): item
        for item in agents
        if isinstance(item, dict) and item.get("name")
    }


def _agent_config_fields(name: str) -> dict:
    config = _agent_config_map().get(name, {})
    if not isinstance(config, dict):
        return {}
    return {
        "system_prompt": config.get("system_prompt"),
        "tools": _as_str_list(config.get("tools")),
        "output_format": config.get("output_format"),
        "max_iterations": config.get("max_iterations"),
        "skills": config.get("skills"),
        "skill_mount": _build_skill_mount(config),
        "mcp_servers": sanitize_mcp_servers_for_response(config.get("mcp_servers") or []),
        "mcp_mounts": _build_mcp_mounts(config),
        "mcp_capability_status": build_mcp_capability_status(config),
        **_workspace_config_fields(config),
    }


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _runtime_meta_map() -> dict[str, Any]:
    registry = get_agent_registry()
    if not registry:
        return {}
    return {
        meta.name: meta
        for meta in registry.list_all()
        if getattr(meta, "name", None)
    }


def _capability_schema_map() -> dict[str, Any]:
    cap_registry = get_capability_registry()
    if not cap_registry:
        return {}
    return {
        schema.name: schema
        for schema in cap_registry.list_all()
        if getattr(schema, "name", None)
    }


def _meta_status(meta: Any | None, fallback: str = "configured") -> str:
    if meta is None:
        return fallback
    status = getattr(meta, "status", fallback)
    return str(getattr(status, "value", status))


def _meta_description(meta: Any | None, config: dict[str, Any]) -> str:
    if meta is not None and getattr(meta, "description", ""):
        return str(meta.description)
    return str(config.get("description") or "")


def _build_tool_mounts(
    tool_names: list[str],
    runtime_metas: dict[str, Any],
    capability_schemas: dict[str, Any],
) -> list[AgentToolMount]:
    mounts: list[AgentToolMount] = []
    for name in tool_names:
        schema = capability_schemas.get(name)
        agent_meta = runtime_metas.get(name)
        mount_type = "agent" if agent_meta else "tool" if schema else "unknown"
        mounts.append(
            AgentToolMount(
                name=name,
                type=mount_type,
                configured=True,
                available=bool(schema or agent_meta),
                description=(
                    str(getattr(agent_meta, "description", ""))
                    if agent_meta
                    else str(getattr(schema, "description", "")) if schema else ""
                ),
                parameters=getattr(schema, "parameters", {}) if schema else {},
            )
        )
    return mounts


def _build_skill_mount(config: dict[str, Any]) -> AgentSkillMount:
    skills = config.get("skills")
    if not isinstance(skills, dict):
        return AgentSkillMount(configured=False)

    items = [
        item
        for item in skills.get("items", [])
        if isinstance(item, dict)
    ] if isinstance(skills.get("items"), list) else []
    return AgentSkillMount(
        configured=True,
        enabled=bool(skills.get("enabled", True)),
        directories=_as_str_list(skills.get("directories")),
        items=items,
        disabled=_as_str_list(skills.get("disabled")),
        strategy=str(skills.get("strategy") or "metadata_and_instructions"),
        item_count=len(items),
    )


def _build_mcp_mounts(config: dict[str, Any]) -> list[AgentMCPMount]:
    servers = config.get("mcp_servers")
    if not isinstance(servers, list):
        return []

    mounts: list[AgentMCPMount] = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        errors = validate_mcp_server_payload(server)
        enabled = bool(server.get("enabled", True))
        status = "disabled" if not enabled else "config_error" if errors else "configured_pending_runtime"
        mounts.append(
            AgentMCPMount(
                name=str(server.get("name") or ""),
                enabled=enabled,
                transport=str(server.get("transport") or "stdio"),
                command=str(server.get("command") or ""),
                description=str(server.get("description") or ""),
                status=status,
                errors=errors,
            )
        )
    return mounts


def _workspace_config_fields(config: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(
        config.get("default_workspace_id")
        or config.get("workspace_id")
        or ""
    ).strip() or None
    workspace_root = str(
        config.get("default_workspace_root")
        or config.get("workspace_root")
        or ""
    ).strip() or None
    return {
        "default_workspace_id": workspace_id,
        "default_workspace_root": workspace_root,
        "workspace_binding": AgentWorkspaceBinding(
            workspace_id=workspace_id,
            workspace_root=workspace_root,
            source="agent_config" if workspace_id or workspace_root else "not_configured",
        ),
    }


def _public_agent_llm_config(config: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    public: dict[str, Any] = {}
    has_values = False
    for key in (
        "provider",
        "model",
        "base_url",
        "temperature",
        "top_p",
        "max_tokens",
        "reasoning_effort",
        "stop_sequences",
        "openai",
        "anthropic",
    ):
        value = config.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if isinstance(value, (dict, list)) and not value:
            continue
        public[key] = value
        has_values = True
    api_key_set = bool(config.get("api_key_set") or str(config.get("api_key") or "").strip())
    if not has_values and not api_key_set:
        return None
    public["api_key_set"] = api_key_set
    public["source"] = source
    return public


def _agent_llm_config(config: dict[str, Any], runtime_meta: Any | None = None) -> dict[str, Any] | None:
    llm = config.get("llm")
    normalized: dict[str, Any] = {}
    if isinstance(llm, dict):
        for key in llm:
            if llm.get(key) is not None:
                normalized[key] = llm.get(key)
    if config.get("model") and "model" not in normalized:
        normalized["model"] = str(config["model"])
    public = _public_agent_llm_config(normalized, source="agent_config")
    if public:
        return public

    runtime_config = getattr(runtime_meta, "runtime_config", None)
    if isinstance(runtime_config, dict) and isinstance(runtime_config.get("llm"), dict):
        return _public_agent_llm_config(runtime_config["llm"], source=str(runtime_config["llm"].get("source") or "global_default"))
    return None


def _runtime_mcp_status(runtime_meta: Any | None) -> dict[str, Any] | None:
    runtime_config = getattr(runtime_meta, "runtime_config", None)
    if isinstance(runtime_config, dict) and isinstance(runtime_config.get("mcp_capability_status"), dict):
        return runtime_config["mcp_capability_status"]
    return None


def _build_agent_info(
    name: str,
    *,
    config: dict[str, Any] | None = None,
    runtime_meta: Any | None = None,
    runtime_metas: dict[str, Any] | None = None,
    capability_schemas: dict[str, Any] | None = None,
) -> AgentInfo:
    config = config if isinstance(config, dict) else {}
    runtime_metas = runtime_metas or _runtime_meta_map()
    capability_schemas = capability_schemas or _capability_schema_map()

    runtime_tools = _as_str_list(getattr(runtime_meta, "capabilities", []))
    configured_tools = _as_str_list(config.get("tools"))
    tool_names = configured_tools or runtime_tools
    llm_config = _agent_llm_config(config, runtime_meta)

    return AgentInfo(
        name=name,
        status=_meta_status(runtime_meta),
        registered=runtime_meta is not None,
        capabilities=runtime_tools or tool_names,
        runtime_tools=runtime_tools,
        tools=tool_names,
        tool_mounts=_build_tool_mounts(tool_names, runtime_metas, capability_schemas),
        description=_meta_description(runtime_meta, config),
        system_prompt=config.get("system_prompt"),
        model=llm_config.get("model") if llm_config else None,
        llm=llm_config,
        output_format=config.get("output_format"),
        max_iterations=config.get("max_iterations"),
        skills=config.get("skills") if isinstance(config.get("skills"), dict) else None,
        skill_mount=_build_skill_mount(config),
        mcp_servers=sanitize_mcp_servers_for_response(config.get("mcp_servers") if isinstance(config.get("mcp_servers"), list) else []),
        mcp_mounts=_build_mcp_mounts(config),
        mcp_capability_status=build_mcp_capability_status(
            config,
            runtime_status=_runtime_mcp_status(runtime_meta),
        ),
        **_workspace_config_fields(config),
    )


def _format_mcp_validation_error(mcp_servers: list[dict]) -> str | None:
    errors = validate_agent_mcp_servers_payload(mcp_servers)
    return "; ".join(errors) if errors else None


def _find_agent_config(agents_list: list[Any], name: str) -> dict[str, Any] | None:
    for agent in agents_list:
        if isinstance(agent, dict) and agent.get("name") == name:
            return agent
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_workspace_root_field(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    if Path(raw).expanduser().is_absolute():
        return "default_workspace_root must be a relative path under ./workspace; use default_workspace_id for managed project workspaces"
    try:
        resolved = resolve_project_path(raw)
    except Exception as exc:
        return f"default_workspace_root is invalid: {exc}"
    workspace_root = default_workspace_root().resolve()
    if not _is_relative_to(resolved, workspace_root):
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
        resolved = (root / path).resolve()
        if not _is_relative_to(resolved, root):
            return "skills paths must stay within the project root"
    return None


def _validate_tools_for_write(
    agent_name: str,
    tools: list[str] | None,
    *,
    existing_tools: list[str] | None = None,
    creating: bool = False,
) -> str | None:
    if tools is None:
        return None
    tool_set = set(tools)
    if agent_name != "agent_manager" and tool_set & AGENT_MANAGEMENT_TOOLS:
        blocked = ", ".join(sorted(tool_set & AGENT_MANAGEMENT_TOOLS))
        return f"Agent 管理工具只能挂载到 agent_manager: {blocked}"
    if creating:
        blocked = sorted(tool_set & HIGH_RISK_TOOLS)
    else:
        blocked = sorted((tool_set - set(existing_tools or [])) & HIGH_RISK_TOOLS)
    if blocked:
        return "普通 Agent API 不能新增高风险工具，请通过 agent_manager 审批: " + ", ".join(blocked)
    return None


async def _reload_agents():
    fn = reload_agent_fn()
    if fn:
        await fn()


async def _save_config_and_reload(data: dict, previous_data: dict) -> None:
    """Persist agents.yaml and reload runtime; rollback the file if reload fails."""

    save_yaml_config("agents.yaml", data)
    _clear_cache()
    try:
        await _reload_agents()
    except Exception as exc:
        save_yaml_config("agents.yaml", previous_data)
        _clear_cache()
        try:
            await _reload_agents()
        except Exception as rollback_exc:  # pragma: no cover - defensive logging path
            print(f"[ERROR] failed to rollback agents.yaml after reload error: {rollback_exc}")
        raise RuntimeError(f"Agent 配置已回滚，热重载失败: {exc}") from exc


def _sanitize_agent_config_for_response(config: dict[str, Any]) -> dict[str, Any]:
    """Return an Agent config copy with secret fields masked for API responses."""

    sanitized = deepcopy(config)
    llm = sanitized.get("llm")
    if isinstance(llm, dict):
        api_key = str(llm.pop("api_key", "") or "").strip()
        llm["api_key_set"] = bool(api_key)
    if "mcp_servers" in sanitized:
        sanitized["mcp_servers"] = sanitize_mcp_servers_for_response(sanitized.get("mcp_servers"))
    return sanitized


def _attach_trusted_workspace_context(payload: dict[str, Any], agent_name: str) -> str | None:
    """Resolve workspace context from trusted server state and drop raw roots."""

    payload.pop("workspace_root", None)
    payload.pop("_trusted_workspace_root", None)

    workspace_id = str(payload.get("workspace_id") or "").strip()
    if workspace_id:
        try:
            workspace = WorkspaceStore().get(workspace_id)
        except WorkspaceNotFoundError:
            return f"workspace not found: {workspace_id}"
        payload["workspace_id"] = workspace.id
        payload["_trusted_workspace_root"] = workspace.root_path
        return None

    session_id = str(payload.get("session_id") or "").strip()
    if session_id:
        session = ChatHistoryStore().get_session(session_id)
        bound_workspace_id = str((session or {}).get("workspace_id") or "").strip()
        if bound_workspace_id:
            try:
                workspace = WorkspaceStore().get(bound_workspace_id)
            except WorkspaceNotFoundError:
                return f"workspace not found: {bound_workspace_id}"
            payload["workspace_id"] = workspace.id
            payload["_trusted_workspace_root"] = workspace.root_path
            return None

        payload["workspace_id"] = session_workspace_id(session_id)
        payload["_trusted_workspace_root"] = str(session_workspace_root(session_id))
        return None

    config = _agent_config_map().get(agent_name, {})
    if not isinstance(config, dict):
        return None
    default_workspace_id = str(config.get("default_workspace_id") or config.get("workspace_id") or "").strip()
    if default_workspace_id:
        try:
            workspace = WorkspaceStore().get(default_workspace_id)
        except WorkspaceNotFoundError:
            return f"workspace not found: {default_workspace_id}"
        payload["workspace_id"] = workspace.id
        payload["_trusted_workspace_root"] = workspace.root_path
        return None

    default_workspace_root = str(config.get("default_workspace_root") or config.get("workspace_root") or "").strip()
    if default_workspace_root:
        root_error = _validate_workspace_root_field(default_workspace_root)
        if root_error:
            return root_error
        payload["workspace_id"] = f"agent-{agent_name}"
        payload["_trusted_workspace_root"] = str(resolve_project_path(default_workspace_root))
    return None


# ─── 读取端点 ─────────────────────────────────────────────


@router.get("/persona-bindings", response_model=APIResponse)
async def get_agent_persona_bindings():
    """Return Agent/session persona bindings from the Agent information architecture side.

    Precedence is request persona_id > session binding > Agent binding > base persona.
    The older /api/personas/bindings endpoints are retained as compatibility aliases.
    """

    data = PersonaBindingService().get_bindings(known_agents=_known_agent_roles())
    return APIResponse(status="ok", data=data)


@router.put("/persona-bindings/agents/{agent_name}", response_model=APIResponse)
async def bind_agent_default_persona(agent_name: str, req: AgentPersonaBindRequest):
    """Bind a default persona to an Agent role."""

    if agent_name not in _known_agent_roles():
        return APIResponse(status="error", message=f"Agent role '{agent_name}' is not configured")
    try:
        binding = PersonaBindingService().bind_agent(agent_name, req.persona_id)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    return APIResponse(status="ok", data=binding)


@router.delete("/persona-bindings/agents/{agent_name}", response_model=APIResponse)
async def unbind_agent_default_persona(agent_name: str):
    """Remove an Agent default persona binding; resolution falls back to base persona."""

    if agent_name not in _known_agent_roles():
        return APIResponse(status="error", message=f"Agent role '{agent_name}' is not configured")
    binding = PersonaBindingService().unbind_agent(agent_name)
    return APIResponse(status="ok", data=binding)


@router.put("/persona-bindings/sessions/{session_id}", response_model=APIResponse)
async def bind_session_persona_from_agent_page(session_id: str, req: AgentPersonaBindRequest):
    """Bind a persona to a session from the Agent page workflow."""

    try:
        binding = PersonaBindingService().bind_session(session_id, req.persona_id)
    except ValueError as exc:
        return APIResponse(status="error", message=str(exc))
    return APIResponse(status="ok", data=binding)


@router.delete("/persona-bindings/sessions/{session_id}", response_model=APIResponse)
async def unbind_session_persona_from_agent_page(session_id: str):
    """Remove a session persona binding."""

    binding = PersonaBindingService().unbind_session(session_id)
    return APIResponse(status="ok", data=binding)



@router.get("", response_model=APIResponse)
async def list_agents():
    """列出所有已注册 Agent 及其状态"""
    registry = get_agent_registry()
    if not registry:
        return APIResponse(status="ok", data=[])

    agents = []
    config_by_name = _agent_config_map()
    runtime_metas = _runtime_meta_map()
    capability_schemas = _capability_schema_map()
    for meta in registry.list_all():
        config = config_by_name.get(meta.name, {})
        agents.append(_build_agent_info(
            meta.name,
            config=config,
            runtime_meta=meta,
            runtime_metas=runtime_metas,
            capability_schemas=capability_schemas,
        ).model_dump())

    return APIResponse(status="ok", data=agents)


@router.get("/configs", response_model=APIResponse)
async def list_agent_configs():
    """Return Agent-centered configuration views for Tools/MCP/Skills/workspace bindings."""

    config_by_name = _agent_config_map()
    runtime_metas = _runtime_meta_map()
    capability_schemas = _capability_schema_map()
    names = sorted(set(config_by_name) | set(runtime_metas))
    payload = [
        _build_agent_info(
            name,
            config=config_by_name.get(name, {}),
            runtime_meta=runtime_metas.get(name),
            runtime_metas=runtime_metas,
            capability_schemas=capability_schemas,
        ).model_dump()
        for name in names
    ]
    return APIResponse(status="ok", data=payload)


@router.get("/capabilities/list", response_model=APIResponse)
async def list_capabilities():
    """列出所有已发现的能力（工具 + Agent），供前端 Agent 编辑时选择 tools"""
    cap_registry = get_capability_registry()
    if not cap_registry:
        return APIResponse(status="ok", data=[])

    capabilities = []
    for schema in cap_registry.list_all():
        capabilities.append({
            "name": schema.name,
            "description": schema.description,
            "parameters": schema.parameters,
        })

    return APIResponse(status="ok", data=capabilities)


@router.get("/{name}/config", response_model=APIResponse)
async def get_agent_config(name: str):
    """Return one Agent-centered configuration view."""

    config_by_name = _agent_config_map()
    runtime_metas = _runtime_meta_map()
    if name not in config_by_name and name not in runtime_metas:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' 不存在")
    return APIResponse(
        status="ok",
        data=_build_agent_info(
            name,
            config=config_by_name.get(name, {}),
            runtime_meta=runtime_metas.get(name),
        ).model_dump(),
    )


@router.get("/{name}", response_model=APIResponse)
async def get_agent(name: str):
    """获取特定 Agent 详情"""
    registry = get_agent_registry()
    if not registry:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' 不存在")

    agent = registry.get(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' 不存在")

    meta = agent.get_metadata()
    config = _agent_config_map().get(name, {})
    return APIResponse(
        status="ok",
        data=_build_agent_info(name, config=config, runtime_meta=meta).model_dump(),
    )


# ─── CRUD 端点 ────────────────────────────────────────────


@router.post("", response_model=APIResponse)
async def create_agent(req: AgentCreateRequest):
    """创建新 Agent，写入 YAML 并热重载"""
    # 读取当前 YAML
    data = load_single_yaml("agents.yaml")
    previous_data = deepcopy(data)
    agents_list = data.get("agents", [])
    if not isinstance(agents_list, list):
        return APIResponse(status="error", message="config/agents.yaml 中 agents 必须是列表")

    # 检查名称唯一性
    for a in agents_list:
        if a.get("name") == req.name:
            return APIResponse(status="error", message=f"Agent '{req.name}' 已存在")

    # 添加新 agent
    tools_error = _validate_tools_for_write(req.name, req.tools, creating=True)
    if tools_error:
        return APIResponse(status="error", message=tools_error)
    if req.skills is not None:
        skills_error = _validate_skill_paths(req.skills.model_dump())
        if skills_error:
            return APIResponse(status="error", message=skills_error)
    root_error = _validate_workspace_root_field(req.default_workspace_root)
    if root_error:
        return APIResponse(status="error", message=root_error)

    mcp_servers = [server.model_dump() for server in req.mcp_servers]
    mcp_error = _format_mcp_validation_error(mcp_servers)
    if mcp_error:
        return APIResponse(status="error", message=mcp_error)

    new_agent = {
        "name": req.name,
        "description": req.description,
        "system_prompt": req.system_prompt,
        "tools": req.tools,
        "output_format": req.output_format,
        "max_iterations": req.max_iterations,
    }
    if req.skills is not None:
        new_agent["skills"] = req.skills.model_dump()
    if mcp_servers:
        new_agent["mcp_servers"] = mcp_servers
    llm_config = _llm_request_payload(req)
    if llm_config:
        new_agent["llm"] = llm_config
    if req.default_workspace_id is not None:
        new_agent["default_workspace_id"] = req.default_workspace_id
    if req.default_workspace_root is not None:
        new_agent["default_workspace_root"] = req.default_workspace_root
    agents_list.append(new_agent)
    data["agents"] = agents_list

    # 写回 YAML 并重载
    try:
        await _save_config_and_reload(data, previous_data)
    except RuntimeError as exc:
        return APIResponse(status="error", message=str(exc))

    return APIResponse(
        status="ok",
        message=f"Agent '{req.name}' 已创建",
        data=_sanitize_agent_config_for_response(new_agent),
    )


@router.put("/{name}", response_model=APIResponse)
async def update_agent(name: str, req: AgentUpdateRequest):
    """更新 Agent 配置，写入 YAML 并热重载"""
    if name == "agent_manager":
        return APIResponse(status="error", message="agent_manager 只能通过受控 agent_manager 工具链修改")

    data = load_single_yaml("agents.yaml")
    previous_data = deepcopy(data)
    agents_list = data.get("agents", [])
    if not isinstance(agents_list, list):
        return APIResponse(status="error", message="config/agents.yaml 中 agents 必须是列表")

    target = None
    for a in agents_list:
        if a.get("name") == name:
            target = a
            break

    if target is None:
        return APIResponse(status="error", message=f"Agent '{name}' 不存在")

    if req.tools is not None:
        tools_error = _validate_tools_for_write(
            name,
            req.tools,
            existing_tools=_as_str_list(target.get("tools")),
            creating=False,
        )
        if tools_error:
            return APIResponse(status="error", message=tools_error)
    if req.skills is not None:
        skills_error = _validate_skill_paths(req.skills.model_dump())
        if skills_error:
            return APIResponse(status="error", message=skills_error)
    if "default_workspace_root" in req.model_fields_set:
        root_error = _validate_workspace_root_field(req.default_workspace_root)
        if root_error:
            return APIResponse(status="error", message=root_error)

    if req.description is not None:
        target["description"] = req.description
    if req.system_prompt is not None:
        target["system_prompt"] = req.system_prompt
    if req.tools is not None:
        target["tools"] = req.tools
    if req.output_format is not None:
        target["output_format"] = req.output_format
    if req.max_iterations is not None:
        target["max_iterations"] = req.max_iterations
    if "skills" in req.model_fields_set:
        if req.skills is None:
            target.pop("skills", None)
        else:
            target["skills"] = req.skills.model_dump()
    if req.mcp_servers is not None:
        mcp_servers = [server.model_dump() for server in req.mcp_servers]
        mcp_error = _format_mcp_validation_error(mcp_servers)
        if mcp_error:
            return APIResponse(status="error", message=mcp_error)
        target["mcp_servers"] = merge_mcp_servers_preserving_masked_env(
            target.get("mcp_servers"),
            mcp_servers,
        )
    if "llm" in req.model_fields_set:
        if req.llm is None or not req.llm.model_fields_set:
            target.pop("llm", None)
        else:
            llm_payload = _llm_request_payload(req)
            if llm_payload:
                existing_llm = target.get("llm") if isinstance(target.get("llm"), dict) else {}
                merged_llm = {**existing_llm, **llm_payload}
                target["llm"] = merged_llm
    elif "model" in req.model_fields_set:
        if req.model is None:
            existing_llm = target.get("llm")
            if isinstance(existing_llm, dict):
                existing_llm.pop("model", None)
                if existing_llm:
                    target["llm"] = existing_llm
                else:
                    target.pop("llm", None)
            else:
                target.pop("model", None)
        else:
            if not isinstance(target.get("llm"), dict):
                target["llm"] = {}
            target["llm"]["model"] = req.model
    if "default_workspace_id" in req.model_fields_set:
        if req.default_workspace_id is None:
            target.pop("default_workspace_id", None)
        else:
            target["default_workspace_id"] = req.default_workspace_id
    if "default_workspace_root" in req.model_fields_set:
        if req.default_workspace_root is None:
            target.pop("default_workspace_root", None)
        else:
            target["default_workspace_root"] = req.default_workspace_root

    data["agents"] = agents_list

    try:
        await _save_config_and_reload(data, previous_data)
    except RuntimeError as exc:
        return APIResponse(status="error", message=str(exc))

    return APIResponse(
        status="ok",
        message=f"Agent '{name}' 已更新",
        data=_sanitize_agent_config_for_response(target),
    )


@router.post("/{name}/mcp/import", response_model=APIResponse)
async def import_agent_mcp_config(name: str, req: AgentMCPImportRequest):
    """Import common MCP config formats into one Agent-scoped mcp_servers list."""

    data = load_single_yaml("agents.yaml")
    previous_data = deepcopy(data)
    agents_list = data.get("agents", [])
    if not isinstance(agents_list, list):
        return APIResponse(status="error", message="config/agents.yaml 中 agents 必须是列表")

    target = _find_agent_config(agents_list, name)
    if target is None:
        return APIResponse(status="error", message=f"Agent '{name}' 不存在")
    if req.apply and name == "agent_manager":
        return APIResponse(status="error", message="agent_manager 只能通过受控 agent_manager 工具链修改")

    parsed = parse_mcp_import_text(
        req.content,
        source_format=req.format,
        source=req.source,
    )
    validation_errors = validate_agent_mcp_servers_payload(parsed.servers)
    errors = [*parsed.errors, *validation_errors]
    preview_servers = (
        merge_imported_mcp_servers(
            target.get("mcp_servers"),
            parsed.servers,
            mode=req.mode,
        )
        if not errors
        else parsed.servers
    )
    payload = {
        "servers": sanitize_mcp_servers_for_response(parsed.servers),
        "validation": {
            "valid": not errors,
            "errors": errors,
        },
        "errors": errors,
        "preview": sanitize_mcp_servers_for_response(preview_servers),
        "mode": req.mode,
        "apply": req.apply,
        "applied": False,
        "source_format": parsed.source_format,
        "detected_shape": parsed.detected_shape,
    }

    if errors:
        return APIResponse(status="error", message="MCP 导入配置无效", data=payload)
    if not req.apply:
        return APIResponse(status="ok", data=payload)

    target["mcp_servers"] = preview_servers
    data["agents"] = agents_list
    try:
        await _save_config_and_reload(data, previous_data)
    except RuntimeError as exc:
        return APIResponse(status="error", message=str(exc), data=payload)

    payload["applied"] = True
    payload["agent"] = _sanitize_agent_config_for_response(target)
    return APIResponse(status="ok", message=f"Agent '{name}' MCP 配置已导入", data=payload)


@router.delete("/{name}", response_model=APIResponse)
async def delete_agent(name: str):
    """删除 Agent，写入 YAML 并热重载"""
    if name in PROTECTED_AGENT_NAMES:
        return APIResponse(status="error", message=f"Agent '{name}' 是内置关键 Agent，不能从管理页删除")

    data = load_single_yaml("agents.yaml")
    previous_data = deepcopy(data)
    agents_list = data.get("agents", [])
    if not isinstance(agents_list, list):
        return APIResponse(status="error", message="config/agents.yaml 中 agents 必须是列表")

    original_len = len(agents_list)
    agents_list = [a for a in agents_list if a.get("name") != name]

    if len(agents_list) == original_len:
        return APIResponse(status="error", message=f"Agent '{name}' 不存在")

    data["agents"] = agents_list

    try:
        await _save_config_and_reload(data, previous_data)
    except RuntimeError as exc:
        return APIResponse(status="error", message=str(exc))

    return APIResponse(status="ok", message=f"Agent '{name}' 已删除")


# ─── 调用端点 ─────────────────────────────────────────────


def _llm_request_payload(req: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    llm = getattr(req, "llm", None)
    if llm is not None:
        dumped = llm.model_dump(
            exclude_none=True,
            exclude_unset=True,
            exclude={"source", "api_key_set"},
        )
        for key, value in dumped.items():
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
                if key == "api_key" and value in MASKED_SECRET_VALUES:
                    continue
            if isinstance(value, dict) and not value:
                continue
            payload[key] = value
    model = str(getattr(req, "model", "") or "").strip()
    if model:
        payload["model"] = model
    return payload


def _extract_agent_response_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("response", "content", "text", "message", "output", "answer"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, dict):
                nested = _extract_agent_response_text(value)
                if nested:
                    return nested
    return str(result)


@router.post("/{name}/invoke", response_model=APIResponse)
async def invoke_agent(name: str, req: AgentInvokeRequest):
    """直接调用某个 Agent（通过 CapabilityRegistry）"""
    cap_registry = get_capability_registry()
    if not cap_registry or name not in cap_registry:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' 不存在")

    try:
        payload = dict(req.data or {})
        workspace_error = _attach_trusted_workspace_context(payload, name)
        if workspace_error:
            return APIResponse(status="error", message=workspace_error)
        message = str(payload.get("message") or payload.get("input") or "").strip()
        memories_used = 0
        if message:
            memory_context, memories_used = await build_memory_context(message)
            if memory_context:
                payload["memory_context"] = memory_context
        result = await cap_registry.execute(name, **payload)
        if message:
            response_text = _extract_agent_response_text(result)
            schedule_memory_reflection(
                user_message=message,
                assistant_text=response_text,
                source=f"agent_invoke:{name}",
                session_id=payload.get("session_id"),
            )
            if isinstance(result, dict):
                result = {**result, "memories_used": memories_used}
        return APIResponse(status="ok", data=result)
    except Exception as e:
        return APIResponse(status="error", message=f"Agent 调用失败: {str(e)}")
