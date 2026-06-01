"""能力库（catalog）路由：Tools / Skills / MCP 三层目录 + 一键装配。

把仓库级能力（已注册 Tools、``skills/`` 目录下的 SKILL.md、``config/mcp_servers.yaml``
模板）统一成「列目录 + 装配到 agent」两类操作，挂载前缀 ``/api/catalog``。

装配复用 ``capabilities.tools.agent_management.UpdateAgentConfigCapability`` 的
落盘 + 热重载链路，不新造写盘逻辑；读取在文件/目录缺失时回退空列表（fallback 原则）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from capabilities.tools.agent_management import UpdateAgentConfigCapability
from core.config import load_single_yaml
from core.mcp import (
    merge_mcp_servers_preserving_masked_env,
    sanitize_mcp_servers_for_response,
    validate_mcp_server_payload,
)
from core.skills import load_skill_file
from ..dependencies import get_agent_registry, get_capability_registry
from ..schemas import APIResponse
from .agents import _build_agent_info

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

VALID_KINDS = {"tools", "skills", "mcp"}
_KIND_ALIASES = {"tool": "tools", "skill": "skills"}

INSTRUCTIONS_PREVIEW_LIMIT = 400


# ─── 配置/目录解析（与 agent_management 一致，便于测试覆盖） ──────────


def _config_dir() -> Path | None:
    configured = os.getenv("AGENTIC_CONFIG_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _skills_root() -> Path:
    configured = os.getenv("AGENTIC_SKILLS_ROOT", "").strip()
    base = Path(configured).expanduser().resolve() if configured else _project_root()
    return base / "skills"


def _agents_list() -> List[Dict[str, Any]]:
    data = load_single_yaml("agents.yaml", config_dir=_config_dir())
    agents = data.get("agents", [])
    return [item for item in agents if isinstance(item, dict)] if isinstance(agents, list) else []


# ─── used_by 计算 ──────────────────────────────────────────────────


def _tool_used_by(agents: List[Dict[str, Any]], tool_name: str) -> List[str]:
    used_by: List[str] = []
    for agent in agents:
        tools = agent.get("tools")
        if isinstance(tools, list) and tool_name in tools:
            name = str(agent.get("name") or "").strip()
            if name:
                used_by.append(name)
    return used_by


def _skill_used_by(agents: List[Dict[str, Any]], slug: str, skill_name: str) -> List[str]:
    target_path = f"skills/{slug}/SKILL.md"
    used_by: List[str] = []
    for agent in agents:
        skills = agent.get("skills")
        if not isinstance(skills, dict):
            continue
        items = skills.get("items", [])
        if not isinstance(items, list):
            continue
        matched = False
        for item in items:
            if isinstance(item, str):
                if item.replace("./", "") == target_path or Path(item).name == "SKILL.md" and slug in item:
                    matched = True
            elif isinstance(item, dict):
                path = str(item.get("path") or "").replace("./", "")
                if path == target_path or (path and slug in path):
                    matched = True
                elif str(item.get("name") or "") == skill_name:
                    matched = True
            if matched:
                break
        if matched:
            name = str(agent.get("name") or "").strip()
            if name:
                used_by.append(name)
    return used_by


def _mcp_used_by(agents: List[Dict[str, Any]], server_name: str) -> List[str]:
    used_by: List[str] = []
    for agent in agents:
        servers = agent.get("mcp_servers")
        if not isinstance(servers, list):
            continue
        names = {
            str(server.get("name") or "").strip()
            for server in servers
            if isinstance(server, dict)
        }
        if server_name in names:
            name = str(agent.get("name") or "").strip()
            if name:
                used_by.append(name)
    return used_by


# ─── 目录项加载 ────────────────────────────────────────────────────


def _load_tools_catalog() -> List[Dict[str, Any]]:
    registry = get_capability_registry()
    if not registry:
        return []
    agents = _agents_list()
    items: List[Dict[str, Any]] = []
    for schema in registry.list_all():
        name = getattr(schema, "name", None)
        if not name:
            continue
        items.append(
            {
                "name": name,
                "description": getattr(schema, "description", "") or "",
                "parameters": getattr(schema, "parameters", {}) or {},
                "kind": "tool",
                "used_by": _tool_used_by(agents, name),
            }
        )
    return items


def _iter_skill_dirs(skills_root: Path) -> List[Path]:
    if not skills_root.is_dir():
        return []
    return sorted(
        path.parent
        for path in skills_root.glob("*/SKILL.md")
        if path.is_file()
    )


def _load_skills_catalog() -> List[Dict[str, Any]]:
    skills_root = _skills_root()
    agents = _agents_list()
    items: List[Dict[str, Any]] = []
    for skill_dir in _iter_skill_dirs(skills_root):
        slug = skill_dir.name
        try:
            meta = load_skill_file(skill_dir / "SKILL.md", base=skills_root.parent)
        except Exception:
            # 损坏/无法解析的 SKILL.md 不应让整个目录列举失败。
            continue
        preview = (meta.instructions or "").strip()
        if len(preview) > INSTRUCTIONS_PREVIEW_LIMIT:
            preview = preview[:INSTRUCTIONS_PREVIEW_LIMIT].rstrip() + "…"
        items.append(
            {
                "name": meta.name,
                "description": meta.description,
                "source": f"skills/{slug}/SKILL.md",
                "instructions_preview": preview,
                "kind": "skill",
                "used_by": _skill_used_by(agents, slug, meta.name),
            }
        )
    return items


def _mcp_templates() -> List[Dict[str, Any]]:
    data = load_single_yaml("mcp_servers.yaml", config_dir=_config_dir())
    servers = data.get("mcp_servers", [])
    return [item for item in servers if isinstance(item, dict)] if isinstance(servers, list) else []


def _load_mcp_catalog() -> List[Dict[str, Any]]:
    agents = _agents_list()
    templates = _mcp_templates()
    masked = sanitize_mcp_servers_for_response(templates)
    items: List[Dict[str, Any]] = []
    for server in masked:
        name = str(server.get("name") or "").strip()
        if not name:
            continue
        items.append(
            {
                "name": name,
                "command": str(server.get("command") or ""),
                "args": server.get("args", []) if isinstance(server.get("args"), list) else [],
                "transport": str(server.get("transport") or "stdio"),
                "description": str(server.get("description") or ""),
                "enabled": bool(server.get("enabled", False)),
                "env": server.get("env", {}) if isinstance(server.get("env"), dict) else {},
                "kind": "mcp",
                "used_by": _mcp_used_by(agents, name),
            }
        )
    return items


# ─── 读取端点 ──────────────────────────────────────────────────────


@router.get("/tools", response_model=APIResponse)
async def list_catalog_tools():
    """列出全部已注册能力（Tools），附 used_by。"""

    return APIResponse(status="ok", data=_load_tools_catalog())


@router.get("/skills", response_model=APIResponse)
async def list_catalog_skills():
    """扫描仓库 ``skills/`` 目录列出 Skills 库，附 used_by。目录缺失返回空列表。"""

    return APIResponse(status="ok", data=_load_skills_catalog())


@router.get("/mcp", response_model=APIResponse)
async def list_catalog_mcp():
    """列出 ``config/mcp_servers.yaml`` MCP 模板（env 脱敏），附 used_by。文件缺失返回空列表。"""

    return APIResponse(status="ok", data=_load_mcp_catalog())


# ─── 装配端点 ──────────────────────────────────────────────────────


class AssembleRequest(BaseModel):
    agent_name: str
    env: Dict[str, str] | None = None


def _find_agent(agents: List[Dict[str, Any]], name: str) -> Dict[str, Any] | None:
    for agent in agents:
        if str(agent.get("name") or "") == name:
            return agent
    return None


def _build_tool_patch(agent: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    existing = agent.get("tools")
    tools = [str(item) for item in existing if isinstance(item, str)] if isinstance(existing, list) else []
    if tool_name not in tools:
        tools.append(tool_name)
    return {"tools": tools}


def _build_skill_patch(agent: Dict[str, Any], slug: str) -> Dict[str, Any]:
    target_path = f"skills/{slug}/SKILL.md"
    existing = agent.get("skills")
    skills: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    raw_items = skills.get("items")
    items: List[Any] = list(raw_items) if isinstance(raw_items, list) else []

    def _has_path(item: Any) -> bool:
        if isinstance(item, str):
            return item.replace("./", "") == target_path
        if isinstance(item, dict):
            return str(item.get("path") or "").replace("./", "") == target_path
        return False

    if not any(_has_path(item) for item in items):
        items.append({"path": target_path})
    skills["items"] = items
    skills["enabled"] = True
    return {"skills": skills}


def _build_mcp_patch(
    agent: Dict[str, Any],
    template: Dict[str, Any],
    env_override: Dict[str, str] | None,
) -> tuple[Dict[str, Any] | None, str | None]:
    server: Dict[str, Any] = {
        "name": str(template.get("name") or ""),
        "command": str(template.get("command") or ""),
        "args": list(template.get("args", [])) if isinstance(template.get("args"), list) else [],
        "transport": str(template.get("transport") or "stdio"),
        "description": str(template.get("description") or ""),
        "enabled": True,
    }
    if str(template.get("url") or "").strip():
        server["url"] = str(template["url"])
    env: Dict[str, str] = {}
    template_env = template.get("env")
    if isinstance(template_env, dict):
        env.update({str(k): str(v) for k, v in template_env.items()})
    if env_override:
        env.update({str(k): str(v) for k, v in env_override.items()})
    if env:
        server["env"] = env

    errors = validate_mcp_server_payload(server)
    if errors:
        return None, "; ".join(errors)

    existing = agent.get("mcp_servers")
    existing_list = [s for s in existing if isinstance(s, dict)] if isinstance(existing, list) else []
    # 去重：同名 server 直接替换为新装配项。
    kept = [s for s in existing_list if str(s.get("name") or "") != server["name"]]
    merged = merge_mcp_servers_preserving_masked_env(existing_list, kept + [server])
    return {"mcp_servers": merged}, None


# ─── 卸下（unassemble）：从 agent 配置移除目录项 ──────────────────────


def _build_tool_unpatch(agent: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    existing = agent.get("tools")
    tools = [str(item) for item in existing if isinstance(item, str)] if isinstance(existing, list) else []
    return {"tools": [t for t in tools if t != tool_name]}


def _build_skill_unpatch(agent: Dict[str, Any], slug: str) -> Dict[str, Any]:
    target_path = f"skills/{slug}/SKILL.md"
    existing = agent.get("skills")
    skills: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    raw_items = skills.get("items")
    items: List[Any] = list(raw_items) if isinstance(raw_items, list) else []

    def _has_path(item: Any) -> bool:
        if isinstance(item, str):
            return item.replace("./", "") == target_path
        if isinstance(item, dict):
            return str(item.get("path") or "").replace("./", "") == target_path
        return False

    remaining = [item for item in items if not _has_path(item)]
    skills["items"] = remaining
    skills["enabled"] = bool(remaining)
    return {"skills": skills}


def _build_mcp_unpatch(agent: Dict[str, Any], server_name: str) -> Dict[str, Any]:
    existing = agent.get("mcp_servers")
    existing_list = [s for s in existing if isinstance(s, dict)] if isinstance(existing, list) else []
    return {"mcp_servers": [s for s in existing_list if str(s.get("name") or "") != server_name]}


@router.post("/{kind}/{name}/assemble", response_model=APIResponse)
async def assemble_capability(kind: str, name: str, req: AssembleRequest):
    """把目录项装配到目标 agent 的配置字段，落盘 + 热重载，返回更新后的 agent 视图。"""

    kind = _KIND_ALIASES.get(kind, kind)
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"未知能力类型: {kind}")

    agent_name = str(req.agent_name or "").strip()
    if not agent_name:
        raise HTTPException(status_code=422, detail="agent_name is required")

    agents = _agents_list()
    agent = _find_agent(agents, agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

    if kind == "tools":
        registry = get_capability_registry()
        if not registry or name not in registry:
            raise HTTPException(status_code=404, detail=f"能力 '{name}' 不在能力库中")
        patch = _build_tool_patch(agent, name)
    elif kind == "skills":
        skill_dir = _skills_root() / name
        if not (skill_dir / "SKILL.md").is_file():
            raise HTTPException(status_code=404, detail=f"Skill '{name}' 不在能力库中")
        patch = _build_skill_patch(agent, name)
    else:  # mcp
        template = _find_agent(_mcp_templates(), name)
        if template is None:
            raise HTTPException(status_code=404, detail=f"MCP server '{name}' 不在能力库中")
        patch, error = _build_mcp_patch(agent, template, req.env)
        if error:
            raise HTTPException(status_code=422, detail=f"MCP 配置无效: {error}")

    cap = UpdateAgentConfigCapability()
    result = await cap.execute(agent_name=agent_name, patch=patch)
    if not result.get("success"):
        message = result.get("error") or "; ".join(result.get("errors") or []) or "装配失败"
        raise HTTPException(status_code=422, detail=message)

    # 用落盘后的最新配置重建 agent 视图。
    updated_agent = _find_agent(_agents_list(), agent_name) or agent
    registry = get_agent_registry()
    runtime_meta = registry.get(agent_name).get_metadata() if registry and registry.get(agent_name) else None
    info = _build_agent_info(agent_name, config=updated_agent, runtime_meta=runtime_meta)
    return APIResponse(
        status="ok",
        message=f"已把 {kind[:-1] if kind != 'mcp' else 'mcp'} '{name}' 装配到 Agent '{agent_name}'",
        data=info.model_dump(),
    )


@router.post("/{kind}/{name}/unassemble", response_model=APIResponse)
async def unassemble_capability(kind: str, name: str, req: AssembleRequest):
    """从目标 agent 的配置字段卸下目录项，落盘 + 热重载，返回更新后的 agent 视图。

    幂等：若该项当前未装配到 agent，直接返回成功（无副作用）。不要求该项仍在能力库中，
    以便随时把历史装配卸下。
    """

    kind = _KIND_ALIASES.get(kind, kind)
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"未知能力类型: {kind}")

    agent_name = str(req.agent_name or "").strip()
    if not agent_name:
        raise HTTPException(status_code=422, detail="agent_name is required")

    agents = _agents_list()
    agent = _find_agent(agents, agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

    if kind == "tools":
        patch = _build_tool_unpatch(agent, name)
    elif kind == "skills":
        patch = _build_skill_unpatch(agent, name)
    else:  # mcp
        patch = _build_mcp_unpatch(agent, name)

    cap = UpdateAgentConfigCapability()
    result = await cap.execute(agent_name=agent_name, patch=patch)
    if not result.get("success"):
        message = result.get("error") or "; ".join(result.get("errors") or []) or "卸下失败"
        raise HTTPException(status_code=422, detail=message)

    updated_agent = _find_agent(_agents_list(), agent_name) or agent
    registry = get_agent_registry()
    runtime_meta = registry.get(agent_name).get_metadata() if registry and registry.get(agent_name) else None
    info = _build_agent_info(agent_name, config=updated_agent, runtime_meta=runtime_meta)
    return APIResponse(
        status="ok",
        message=f"已从 Agent '{agent_name}' 卸下 {kind[:-1] if kind != 'mcp' else 'mcp'} '{name}'",
        data=info.model_dump(),
    )
