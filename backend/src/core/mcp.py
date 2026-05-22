"""MCP server configuration helpers.

This module validates and formats MCP server definitions.  It does not start
external MCP processes yet; the generic in-process Agent receives the sanitized
configuration so adapters for Codex/Claude/native MCP clients can consume it or
report a clear degraded mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


SUPPORTED_MCP_TRANSPORTS = {"stdio", "sse", "http", "streamable_http"}


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


def normalize_agent_mcp_servers(agent_config: Dict[str, Any]) -> List[MCPServerConfig]:
    """Return validated enabled MCP servers from one agent config only.

    The effective runtime config is agent-scoped.  Callers that support
    templates/defaults must explicitly merge/inherit them into ``agent_config``
    before creating the agent.
    """

    servers: Any = agent_config.get("mcp_servers", [])
    if isinstance(servers, dict):
        servers = [{"name": name, **value} if isinstance(value, dict) else {"name": name} for name, value in servers.items()]
    if not isinstance(servers, list):
        return []

    normalized: List[MCPServerConfig] = []
    seen: set[str] = set()
    for item in servers:
        if not isinstance(item, dict) or not bool(item.get("enabled", True)):
            continue
        name = str(item.get("name") or "").strip()
        command = str(item.get("command") or "").strip()
        if not name or not command or name in seen:
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
                transport=str(item.get("transport") or "stdio"),
            )
        )
        seen.add(name)
    return normalized


def validate_mcp_server_payload(server: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not str(server.get("name") or "").strip():
        errors.append("name is required")
    if bool(server.get("enabled", True)) and not str(server.get("command") or "").strip():
        errors.append("command is required when server is enabled")
    args = server.get("args", [])
    if args is not None and not isinstance(args, list):
        errors.append("args must be a list of strings")
    elif isinstance(args, list) and any(not isinstance(arg, str) for arg in args):
        errors.append("args must be a list of strings")
    env = server.get("env", {})
    if env is not None and not isinstance(env, dict):
        errors.append("env must be an object")
    transport = str(server.get("transport") or "stdio")
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


def build_mcp_capability_status(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """Return an explainable status for agent-scoped MCP configuration.

    This backend intentionally does not launch MCP servers yet. The status tells
    API/UI callers whether config exists, whether it is valid, and whether tools
    are actually connected.
    """

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
            "errors": ["mcp_servers must be a list"],
            "message": "MCP 配置无效：mcp_servers 必须是列表。当前不会启动 MCP 进程。",
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
            "errors": errors,
            "message": "MCP 配置存在错误；后端不会自动启动 MCP 进程，也不会把这些 server 暴露成可调用工具。",
        }
    if enabled_count > 0:
        return {
            "state": "configured_not_connected",
            "configured_servers": configured_count,
            "enabled_servers": enabled_count,
            "connected_tools": 0,
            "errors": [],
            "message": "MCP server 已配置并会注入 Agent 上下文，但当前后端不会自动启动 MCP 进程；尚未注册为可调用工具。",
        }
    if configured_count > 0:
        return {
            "state": "disabled",
            "configured_servers": configured_count,
            "enabled_servers": 0,
            "connected_tools": 0,
            "errors": [],
            "message": "仅存在禁用的 MCP server 配置；运行时不会连接或暴露工具。",
        }
    return {
        "state": "not_configured",
        "configured_servers": 0,
        "enabled_servers": 0,
        "connected_tools": 0,
        "errors": [],
        "message": "该 Agent 未配置 MCP server。",
    }


def format_mcp_servers_for_prompt(servers: List[MCPServerConfig]) -> str:
    if not servers:
        return ""
    lines = [
        "# MCP Servers configured for this runtime",
        "These MCP server definitions were passed to the agent startup context. This generic backend does not automatically expose them as callable tools unless an MCP adapter/client registers their tools in CapabilityRegistry. If tools are unavailable, clearly say MCP is configured but not connected rather than inventing results.",
    ]
    for server in servers:
        suffix = " ".join(server.args).strip()
        cmd = f"{server.command} {suffix}".strip()
        env_keys = ", ".join(sorted(server.env)) if server.env else "none"
        desc = f" — {server.description}" if server.description else ""
        lines.append(f"- {server.name}{desc}: transport={server.transport}, command={cmd}, cwd={server.cwd or '-'}, env_keys={env_keys}")
    return "\n".join(lines)

