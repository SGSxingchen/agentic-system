"""Agent-scoped MCP proxy capabilities.

The project keeps MCP server definitions on each Agent.  This module turns each
enabled server into one local Capability that can list and call remote MCP
tools through the official Python MCP SDK when it is installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .capability.base import CapabilityBase, CapabilitySchema
from .mcp import MCPServerConfig


MCP_PROXY_PREFIX = "mcp__"
DEFAULT_MCP_TIMEOUT_SECONDS = 10.0
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def is_mcp_sdk_available() -> bool:
    """Return whether the optional official MCP SDK is importable."""

    return importlib.util.find_spec("mcp") is not None


def sanitize_mcp_tool_name_part(value: str, *, fallback: str) -> str:
    text = _SAFE_NAME_RE.sub("_", str(value or "").strip()).strip("_")
    return text or fallback


def build_mcp_proxy_tool_name(agent_name: str, server_name: str) -> str:
    """Build a stable OpenAI/Anthropic-compatible tool name for one server."""

    agent = sanitize_mcp_tool_name_part(agent_name, fallback="agent")
    server = sanitize_mcp_tool_name_part(server_name, fallback="server")
    raw = f"{MCP_PROXY_PREFIX}{agent}__{server}"
    if len(raw) <= 64:
        return raw

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    agent = agent[:18].rstrip("_") or "agent"
    server = server[:24].rstrip("_") or "server"
    return f"{MCP_PROXY_PREFIX}{agent}__{server}__{digest}"[:64]


def is_mcp_proxy_capability_name(name: str) -> bool:
    return str(name or "").startswith(MCP_PROXY_PREFIX)


def create_agent_mcp_proxy_capabilities(
    agent_name: str,
    servers: List[MCPServerConfig],
    *,
    project_root: Path,
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS,
) -> List["MCPServerProxyCapability"]:
    """Create one proxy capability per enabled MCP server for this Agent only."""

    return [
        MCPServerProxyCapability(
            agent_name=agent_name,
            server=server,
            project_root=project_root,
            timeout_seconds=timeout_seconds,
        )
        for server in servers
        if server.enabled
    ]


def build_agent_mcp_runtime_status(
    agent_name: str,
    servers: List[MCPServerConfig],
    *,
    project_root: Path,
) -> Dict[str, Any]:
    """Return startup status for Agent-scoped MCP proxies without exposing env."""

    configured_servers = len(servers)
    enabled_servers = len([server for server in servers if server.enabled])
    sdk_available = is_mcp_sdk_available()
    server_statuses: Dict[str, Dict[str, Any]] = {}
    registered_tools = 0
    connected_tools = 0
    errors: List[str] = []

    for server in servers:
        if not server.enabled:
            server_statuses[server.name] = {
                "state": "disabled",
                "transport": server.transport,
                "tool": None,
                "errors": [],
            }
            continue

        proxy_name = build_mcp_proxy_tool_name(agent_name, server.name)
        if server.transport != "stdio":
            message = f"MCP transport '{server.transport}' is not supported by the local proxy yet"
            server_statuses[server.name] = {
                "state": "unsupported_transport",
                "transport": server.transport,
                "tool": proxy_name,
                "errors": [message],
            }
            errors.append(f"{server.name}: {message}")
            continue

        cwd_error = _validate_mcp_cwd(server, project_root)
        if cwd_error:
            server_statuses[server.name] = {
                "state": "config_error",
                "transport": server.transport,
                "tool": proxy_name,
                "errors": [cwd_error],
            }
            errors.append(f"{server.name}: {cwd_error}")
            continue

        registered_tools += 1
        if not sdk_available:
            message = "Python MCP SDK is not installed; install dependency 'mcp' to enable this proxy"
            server_statuses[server.name] = {
                "state": "adapter_unavailable",
                "transport": server.transport,
                "tool": proxy_name,
                "errors": [message],
            }
            errors.append(f"{server.name}: {message}")
            continue

        connected_tools += 1
        server_statuses[server.name] = {
            "state": "proxy_available",
            "transport": server.transport,
            "tool": proxy_name,
            "errors": [],
        }

    if configured_servers == 0:
        state = "not_configured"
        message = "Agent has no MCP server configuration."
    elif enabled_servers == 0:
        state = "disabled"
        message = "Only disabled MCP server configurations are present."
    elif registered_tools > 0 and connected_tools == 0 and any(
        item["state"] == "adapter_unavailable" for item in server_statuses.values()
    ):
        state = "adapter_unavailable"
        message = "MCP proxy tools are registered, but the Python MCP SDK is not installed."
    elif registered_tools > 0 and errors:
        state = "partial"
        message = "Some Agent-scoped MCP server proxies are available; some are degraded."
    elif registered_tools > 0:
        state = "proxy_available"
        message = "Agent-scoped MCP server proxies are registered as callable tools."
    elif errors:
        state = "config_error"
        message = "MCP servers are configured, but no proxy can be registered."
    else:
        state = "configured"
        message = "MCP servers are configured."

    return {
        "state": state,
        "configured_servers": configured_servers,
        "enabled_servers": enabled_servers,
        "registered_tools": registered_tools,
        "connected_tools": connected_tools,
        "servers": server_statuses,
        "errors": errors,
        "message": message,
    }


class MCPServerProxyCapability(CapabilityBase):
    """A local tool that proxies one Agent-owned MCP server."""

    def __init__(
        self,
        *,
        agent_name: str,
        server: MCPServerConfig,
        project_root: Path,
        timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__({})
        self.agent_name = agent_name
        self.server = server
        self.project_root = Path(project_root).resolve()
        self.timeout_seconds = float(timeout_seconds)
        self._name = build_mcp_proxy_tool_name(agent_name, server.name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        base = (
            f"Agent-scoped MCP proxy for server '{self.server.name}'. "
            "Use operation='list_tools' to inspect remote tools, then "
            "operation='call_tool' with tool_name and arguments."
        )
        if self.server.description:
            base += f" Server note: {self.server.description}"
        return base

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["list_tools", "call_tool"],
                        "description": "Whether to list remote MCP tools or call one remote tool.",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Remote MCP tool name. Required for call_tool.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments passed to the remote MCP tool.",
                        "additionalProperties": True,
                    },
                },
                "required": ["operation"],
                "additionalProperties": False,
            },
            returns="MCP list_tools or call_tool result, normalized to JSON-compatible data.",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=12000,
        )

    async def execute(
        self,
        operation: str,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        operation = str(operation or "").strip()
        if operation not in {"list_tools", "call_tool"}:
            return {"error": "invalid_operation", "message": "operation must be list_tools or call_tool"}
        if self.server.transport != "stdio":
            return {
                "error": "unsupported_transport",
                "transport": self.server.transport,
                "message": "Only stdio MCP servers are supported by this backend proxy currently.",
            }
        if not is_mcp_sdk_available():
            return {
                "error": "mcp_sdk_unavailable",
                "message": "Python MCP SDK is not installed. Install dependency 'mcp' and restart the backend.",
            }
        if operation == "call_tool" and not str(tool_name or "").strip():
            return {"error": "tool_name_required", "message": "tool_name is required for call_tool."}

        cwd_error = _validate_mcp_cwd(self.server, self.project_root)
        if cwd_error:
            return {"error": "mcp_cwd_not_allowed", "message": cwd_error}

        try:
            if operation == "list_tools":
                result = await self._run_with_session(lambda session: session.list_tools())
                tools = [
                    {
                        "name": getattr(tool, "name", ""),
                        "description": getattr(tool, "description", "") or "",
                        "input_schema": _json_compatible(
                            getattr(tool, "inputSchema", None)
                            or getattr(tool, "input_schema", None)
                            or {}
                        ),
                    }
                    for tool in getattr(result, "tools", []) or []
                ]
                return {
                    "server": self.server.name,
                    "operation": "list_tools",
                    "tools": tools,
                }

            result = await self._run_with_session(
                lambda session: session.call_tool(
                    str(tool_name).strip(),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
            return {
                "server": self.server.name,
                "operation": "call_tool",
                "tool_name": str(tool_name).strip(),
                "result": _json_compatible(result),
            }
        except Exception as exc:
            return {
                "error": "mcp_proxy_failed",
                "server": self.server.name,
                "operation": operation,
                "message": str(exc),
            }

    async def _run_with_session(self, action: Any) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.server.command,
            args=list(self.server.args or []),
            env={**os.environ, **(self.server.env or {})},
            cwd=str(_resolve_mcp_cwd(self.server, self.project_root)),
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), timeout=self.timeout_seconds)
                return await asyncio.wait_for(action(session), timeout=self.timeout_seconds)


def _resolve_mcp_cwd(server: MCPServerConfig, project_root: Path) -> Path:
    raw = str(server.cwd or "").strip()
    if not raw:
        return Path(project_root).resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(project_root).resolve() / path
    return path.resolve()


def _validate_mcp_cwd(server: MCPServerConfig, project_root: Path) -> Optional[str]:
    path = _resolve_mcp_cwd(server, project_root)
    root = Path(project_root).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return "MCP server cwd must stay within the project root"
    return None


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_compatible(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_compatible(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_compatible(value.model_dump())
    if is_dataclass(value):
        return _json_compatible(asdict(value))
    if hasattr(value, "__dict__"):
        return _json_compatible(vars(value))
    return str(value)
