"""智能体管理路由

端点:
- GET  /api/agents              — 列出所有已注册 Agent
- GET  /api/agents/{name}       — 获取特定 Agent 详情
- POST /api/agents              — 创建新 Agent
- PUT  /api/agents/{name}       — 更新 Agent 配置
- DELETE /api/agents/{name}     — 删除 Agent
- POST /api/agents/{name}/invoke — 直接调用某个 Agent
- GET  /api/capabilities        — 列出所有可用能力（供 Agent 选择 tools）
"""
from fastapi import APIRouter, HTTPException

from ..schemas import (
    APIResponse,
    AgentInfo,
    AgentInvokeRequest,
    AgentCreateRequest,
    AgentUpdateRequest,
)
from ..dependencies import get_agent_registry, get_capability_registry, reload_agent_fn
from core.config import load_single_yaml, save_yaml_config
from core.mcp import validate_mcp_server_payload

router = APIRouter(prefix="/api/agents", tags=["agents"])


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
        "output_format": config.get("output_format"),
        "max_iterations": config.get("max_iterations"),
        "skills": config.get("skills"),
        "mcp_servers": config.get("mcp_servers") or [],
    }


async def _reload_agents():
    fn = reload_agent_fn()
    if fn:
        await fn()


# ─── 读取端点 ─────────────────────────────────────────────


@router.get("", response_model=APIResponse)
async def list_agents():
    """列出所有已注册 Agent 及其状态"""
    registry = get_agent_registry()
    if not registry:
        return APIResponse(status="ok", data=[])

    agents = []
    config_by_name = _agent_config_map()
    for meta in registry.list_all():
        config = config_by_name.get(meta.name, {})
        agents.append(
            AgentInfo(
                name=meta.name,
                status=meta.status.value,
                capabilities=meta.capabilities,
                description=meta.description,
                system_prompt=config.get("system_prompt") if isinstance(config, dict) else None,
                output_format=config.get("output_format") if isinstance(config, dict) else None,
                max_iterations=config.get("max_iterations") if isinstance(config, dict) else None,
                skills=config.get("skills") if isinstance(config, dict) else None,
                mcp_servers=config.get("mcp_servers") if isinstance(config, dict) else [],
            ).model_dump()
        )

    return APIResponse(status="ok", data=agents)


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
    info = AgentInfo(
        name=meta.name,
        status=meta.status.value,
        capabilities=meta.capabilities,
        description=meta.description,
        **_agent_config_fields(name),
    )

    return APIResponse(status="ok", data=info.model_dump())


# ─── CRUD 端点 ────────────────────────────────────────────


@router.post("", response_model=APIResponse)
async def create_agent(req: AgentCreateRequest):
    """创建新 Agent，写入 YAML 并热重载"""
    # 读取当前 YAML
    data = load_single_yaml("agents.yaml")
    agents_list = data.get("agents", [])

    # 检查名称唯一性
    for a in agents_list:
        if a.get("name") == req.name:
            return APIResponse(status="error", message=f"Agent '{req.name}' 已存在")

    # 添加新 agent
    mcp_servers = [server.model_dump() for server in req.mcp_servers]
    for server in mcp_servers:
        errors = validate_mcp_server_payload(server)
        if errors:
            return APIResponse(status="error", message=f"MCP server '{server.get('name') or '<unnamed>'}' 配置无效: {', '.join(errors)}")

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
    agents_list.append(new_agent)
    data["agents"] = agents_list

    # 写回 YAML 并重载
    save_yaml_config("agents.yaml", data)
    _clear_cache()
    await _reload_agents()

    return APIResponse(status="ok", message=f"Agent '{req.name}' 已创建", data=new_agent)


@router.put("/{name}", response_model=APIResponse)
async def update_agent(name: str, req: AgentUpdateRequest):
    """更新 Agent 配置，写入 YAML 并热重载"""
    data = load_single_yaml("agents.yaml")
    agents_list = data.get("agents", [])

    target = None
    for a in agents_list:
        if a.get("name") == name:
            target = a
            break

    if target is None:
        return APIResponse(status="error", message=f"Agent '{name}' 不存在")

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
    if req.skills is not None:
        target["skills"] = req.skills.model_dump()
    if req.mcp_servers is not None:
        mcp_servers = [server.model_dump() for server in req.mcp_servers]
        for server in mcp_servers:
            errors = validate_mcp_server_payload(server)
            if errors:
                return APIResponse(status="error", message=f"MCP server '{server.get('name') or '<unnamed>'}' 配置无效: {', '.join(errors)}")
        target["mcp_servers"] = mcp_servers

    data["agents"] = agents_list

    save_yaml_config("agents.yaml", data)
    _clear_cache()
    await _reload_agents()

    return APIResponse(status="ok", message=f"Agent '{name}' 已更新", data=target)


@router.delete("/{name}", response_model=APIResponse)
async def delete_agent(name: str):
    """删除 Agent，写入 YAML 并热重载"""
    data = load_single_yaml("agents.yaml")
    agents_list = data.get("agents", [])

    original_len = len(agents_list)
    agents_list = [a for a in agents_list if a.get("name") != name]

    if len(agents_list) == original_len:
        return APIResponse(status="error", message=f"Agent '{name}' 不存在")

    data["agents"] = agents_list

    save_yaml_config("agents.yaml", data)
    _clear_cache()
    await _reload_agents()

    return APIResponse(status="ok", message=f"Agent '{name}' 已删除")


# ─── 调用端点 ─────────────────────────────────────────────


@router.post("/{name}/invoke", response_model=APIResponse)
async def invoke_agent(name: str, req: AgentInvokeRequest):
    """直接调用某个 Agent（通过 CapabilityRegistry）"""
    cap_registry = get_capability_registry()
    if not cap_registry or name not in cap_registry:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' 不存在")

    try:
        result = await cap_registry.execute(name, **req.data)
        return APIResponse(status="ok", data=result)
    except Exception as e:
        return APIResponse(status="error", message=f"Agent 调用失败: {str(e)}")


# ─── 能力列表端点 ─────────────────────────────────────────


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
