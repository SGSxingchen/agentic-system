"""MCP server configuration helpers.

This module validates and formats MCP server definitions.  It does not start
external MCP processes yet; the generic in-process Agent receives the sanitized
configuration so adapters for Codex/Claude/native MCP clients can consume it or
report a clear degraded mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
    env = server.get("env", {})
    if env is not None and not isinstance(env, dict):
        errors.append("env must be an object")
    return errors


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

