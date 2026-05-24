"""Agent-scoped MCP server configuration helpers.

MCP server definitions belong to one Agent.  This module validates, normalizes,
sanitizes, and formats those definitions.  Runtime proxy capabilities are
implemented in ``core.mcp_adapter``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List


SUPPORTED_MCP_TRANSPORTS = {"stdio", "sse", "http", "streamable_http"}
MASKED_MCP_ENV_VALUE = "********"
MASKED_MCP_ENV_VALUES = {MASKED_MCP_ENV_VALUE, "***", "**********", "<masked>"}


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    cwd: str = ""
    description: str = ""
    transport: str = "stdio"
    url: str = ""


def normalize_agent_mcp_servers(agent_config: Dict[str, Any]) -> List[MCPServerConfig]:
    """Return validated enabled MCP servers from one agent config only."""

    servers: Any = agent_config.get("mcp_servers", [])
    if isinstance(servers, dict):
        servers = [
            {"name": name, **value} if isinstance(value, dict) else {"name": name}
            for name, value in servers.items()
        ]
    if not isinstance(servers, list):
        return []

    normalized: List[MCPServerConfig] = []
    seen: set[str] = set()
    for item in servers:
        if not isinstance(item, dict) or not bool(item.get("enabled", True)):
            continue
        name = str(item.get("name") or "").strip()
        command = str(item.get("command") or "").strip()
        transport = str(item.get("transport") or "stdio")
        url = str(item.get("url") or "").strip()
        if not name or name in seen:
            continue
        if transport == "stdio" and not command:
            continue
        if transport != "stdio" and not (command or url):
            continue
        args_raw = item.get("args", [])
        if isinstance(args_raw, str):
            args = [args_raw]
        elif isinstance(args_raw, list):
            args = [str(arg) for arg in args_raw]
        else:
            args = []
        env_raw = item.get("env", {})
        env = {str(k): str(v) for k, v in env_raw.items()} if isinstance(env_raw, dict) else {}
        normalized.append(
            MCPServerConfig(
                name=name,
                command=command,
                args=args,
                env=env,
                enabled=True,
                cwd=str(item.get("cwd") or ""),
                description=str(item.get("description") or ""),
                transport=transport,
                url=url,
            )
        )
        seen.add(name)
    return normalized


def validate_mcp_server_payload(server: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not str(server.get("name") or "").strip():
        errors.append("name is required")
    transport = str(server.get("transport") or "stdio")
    if (
        bool(server.get("enabled", True))
        and (transport == "stdio" or transport not in SUPPORTED_MCP_TRANSPORTS)
        and not str(server.get("command") or "").strip()
    ):
        errors.append("command is required when server is enabled")
    if (
        bool(server.get("enabled", True))
        and transport in SUPPORTED_MCP_TRANSPORTS
        and transport != "stdio"
        and not str(server.get("command") or "").strip()
        and not str(server.get("url") or "").strip()
    ):
        errors.append("url is required when non-stdio server is enabled")
    args = server.get("args", [])
    if args is not None and not isinstance(args, list):
        errors.append("args must be a list of strings")
    elif isinstance(args, list) and any(not isinstance(arg, str) for arg in args):
        errors.append("args must be a list of strings")
    env = server.get("env", {})
    if env is not None and not isinstance(env, dict):
        errors.append("env must be an object")
    if transport not in SUPPORTED_MCP_TRANSPORTS:
        errors.append("transport must be one of http, sse, stdio, streamable_http")
    return errors


def validate_agent_mcp_servers_payload(servers: Any) -> List[str]:
    """Validate an agent-scoped MCP server list for API writes."""

    if servers is None:
        return []
    if not isinstance(servers, list):
        return ["mcp_servers must be a list"]

    errors: List[str] = []
    seen: set[str] = set()
    for item in servers:
        if not isinstance(item, dict):
            errors.append("MCP server '<invalid>' 配置无效: server must be an object")
            continue
        name = str(item.get("name") or "").strip()
        server_errors = validate_mcp_server_payload(item)
        if name and name in seen:
            server_errors.append("duplicate server name")
        if name:
            seen.add(name)
        label = name or "<unnamed>"
        for error in server_errors:
            errors.append(f"MCP server '{label}' 配置无效: {error}")
    return errors


def sanitize_mcp_servers_for_response(servers: Any) -> List[Dict[str, Any]]:
    """Return MCP server configs with env values masked for API/tool responses."""

    if isinstance(servers, dict):
        servers = [
            {"name": name, **value} if isinstance(value, dict) else {"name": name}
            for name, value in servers.items()
        ]
    if not isinstance(servers, list):
        return []

    sanitized: List[Dict[str, Any]] = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        item = deepcopy(server)
        env = item.get("env")
        if isinstance(env, dict):
            item["env"] = {str(key): MASKED_MCP_ENV_VALUE for key in env}
        sanitized.append(item)
    return sanitized


def is_masked_mcp_env_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text in MASKED_MCP_ENV_VALUES or (bool(text) and set(text) == {"*"})


def merge_mcp_servers_preserving_masked_env(
    existing_servers: Any,
    incoming_servers: Any,
) -> List[Dict[str, Any]]:
    """Preserve stored MCP env values when API clients echo masked values."""

    existing_list = existing_servers if isinstance(existing_servers, list) else []
    incoming_list = incoming_servers if isinstance(incoming_servers, list) else []
    existing_by_name = {
        str(server.get("name") or "").strip(): server
        for server in existing_list
        if isinstance(server, dict) and str(server.get("name") or "").strip()
    }

    merged: List[Dict[str, Any]] = []
    for server in incoming_list:
        if not isinstance(server, dict):
            continue
        item = deepcopy(server)
        name = str(item.get("name") or "").strip()
        env = item.get("env")
        existing_env = existing_by_name.get(name, {}).get("env") if name else None
        if isinstance(env, dict) and isinstance(existing_env, dict):
            next_env: Dict[str, Any] = {}
            for key, value in env.items():
                key_text = str(key)
                if is_masked_mcp_env_value(value) and key_text in existing_env:
                    next_env[key_text] = existing_env[key_text]
                else:
                    next_env[key_text] = value
            item["env"] = next_env
        merged.append(item)
    return merged


def build_mcp_capability_status(
    agent_config: Dict[str, Any],
    runtime_status: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return an explainable status for agent-scoped MCP configuration."""

    raw_servers = agent_config.get("mcp_servers", [])
    if raw_servers is None:
        raw_servers = []
    if isinstance(raw_servers, dict):
        raw_servers = [
            {"name": name, **value} if isinstance(value, dict) else {"name": name}
            for name, value in raw_servers.items()
        ]
    if not isinstance(raw_servers, list):
        return {
            "state": "config_error",
            "configured_servers": 0,
            "enabled_servers": 0,
            "connected_tools": 0,
            "registered_tools": 0,
            "errors": ["mcp_servers must be a list"],
            "message": "MCP 配置无效：mcp_servers 必须是列表。",
        }

    errors = validate_agent_mcp_servers_payload(raw_servers)
    normalized = normalize_agent_mcp_servers({"mcp_servers": raw_servers})
    configured_count = len(raw_servers)
    enabled_count = len(normalized)
    if errors:
        return {
            "state": "config_error",
            "configured_servers": configured_count,
            "enabled_servers": enabled_count,
            "connected_tools": 0,
            "registered_tools": 0,
            "errors": errors,
            "message": "MCP 配置存在校验错误；不会注册 MCP 代理工具。",
        }
    if runtime_status:
        status = dict(runtime_status)
        status["configured_servers"] = configured_count
        status["enabled_servers"] = enabled_count
        status.setdefault("connected_tools", status.get("registered_tools", 0))
        status.setdefault("registered_tools", status.get("connected_tools", 0))
        status.setdefault("errors", [])
        return status
    if enabled_count > 0:
        return {
            "state": "configured_pending_runtime",
            "configured_servers": configured_count,
            "enabled_servers": enabled_count,
            "connected_tools": 0,
            "registered_tools": 0,
            "errors": [],
            "message": "MCP server 已配置；运行时会尝试注册 Agent 作用域代理工具。",
        }
    if configured_count > 0:
        return {
            "state": "disabled",
            "configured_servers": configured_count,
            "enabled_servers": 0,
            "connected_tools": 0,
            "registered_tools": 0,
            "errors": [],
            "message": "仅存在已禁用的 MCP server 配置；运行时不会注册工具。",
        }
    return {
        "state": "not_configured",
        "configured_servers": 0,
        "enabled_servers": 0,
        "connected_tools": 0,
        "registered_tools": 0,
        "errors": [],
        "message": "该 Agent 未配置 MCP server。",
    }


def format_mcp_servers_for_prompt(servers: List[MCPServerConfig]) -> str:
    if not servers:
        return ""
    lines = [
        "# MCP Servers configured for this runtime",
        (
            "These MCP server definitions belong only to this Agent. When the "
            "MCP adapter is available, the backend registers one Agent-scoped "
            "proxy tool per enabled stdio server. Use the proxy tool to list "
            "remote tools before calling them. If a proxy is unavailable or "
            "returns an error, report that state instead of inventing MCP results."
        ),
    ]
    for server in servers:
        suffix = " ".join(server.args).strip()
        cmd = f"{server.command} {suffix}".strip()
        env_keys = ", ".join(sorted(server.env)) if server.env else "none"
        desc = f" - {server.description}" if server.description else ""
        endpoint = server.url or "-"
        lines.append(
            f"- {server.name}{desc}: transport={server.transport}, "
            f"command={cmd}, url={endpoint}, cwd={server.cwd or '-'}, env_keys={env_keys}"
        )
    return "\n".join(lines)
