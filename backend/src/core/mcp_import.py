"""Import helpers for common MCP server configuration formats."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from .mcp import merge_mcp_servers_preserving_masked_env


@dataclass(frozen=True)
class MCPImportParseResult:
    """Normalized MCP import parse result."""

    servers: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    source_format: str = "auto"
    detected_shape: str = ""


def parse_mcp_import_text(
    content: str,
    *,
    source_format: str | None = None,
    source: str | None = None,
) -> MCPImportParseResult:
    """Parse JSON/YAML MCP config text into the project mcp_servers shape."""

    text = str(content or "").strip()
    if not text:
        return MCPImportParseResult(errors=["MCP import content is empty"])

    requested_format = _normalize_source_format(source_format, source)
    parsed_format = requested_format
    if requested_format == "json":
        try:
            parsed = json.loads(text)
        except Exception:
            return MCPImportParseResult(errors=["MCP import content is not valid JSON"])
    elif requested_format == "yaml":
        try:
            parsed = yaml.safe_load(text)
        except Exception:
            return MCPImportParseResult(errors=["MCP import content is not valid YAML"])
    else:
        try:
            parsed = json.loads(text)
            parsed_format = "json"
        except Exception:
            try:
                parsed = yaml.safe_load(text)
                parsed_format = "yaml"
            except Exception:
                return MCPImportParseResult(
                    errors=["MCP import content is not valid JSON or YAML"]
                )

    return parse_mcp_import_object(parsed, source_format=parsed_format)


def parse_mcp_import_object(
    payload: Any,
    *,
    source_format: str = "object",
) -> MCPImportParseResult:
    """Normalize supported MCP config object shapes."""

    raw_servers, shape, shape_errors = _extract_server_collection(payload)
    if shape_errors:
        return MCPImportParseResult(
            errors=shape_errors,
            source_format=source_format,
            detected_shape=shape,
        )

    if isinstance(raw_servers, dict):
        iterable = raw_servers.items()
    elif isinstance(raw_servers, list):
        iterable = enumerate(raw_servers)
    else:
        return MCPImportParseResult(
            errors=["MCP server collection must be an object or list"],
            source_format=source_format,
            detected_shape=shape,
        )

    servers: List[Dict[str, Any]] = []
    errors: List[str] = []
    for key, raw_server in iterable:
        if not isinstance(raw_server, dict):
            errors.append("MCP server item must be an object")
            continue
        server = _normalize_imported_server(raw_server, name_hint=str(key))
        if server is None:
            errors.append("MCP server name is required")
            continue
        servers.append(server)

    return MCPImportParseResult(
        servers=servers,
        errors=errors,
        source_format=source_format,
        detected_shape=shape,
    )


def merge_imported_mcp_servers(
    existing_servers: Any,
    imported_servers: Any,
    *,
    mode: str = "merge",
) -> List[Dict[str, Any]]:
    """Return the post-import mcp_servers list for merge or replace mode."""

    if mode not in {"merge", "replace"}:
        raise ValueError("mode must be merge or replace")

    existing_list = existing_servers if isinstance(existing_servers, list) else []
    incoming_list = imported_servers if isinstance(imported_servers, list) else []
    incoming = merge_mcp_servers_preserving_masked_env(existing_list, incoming_list)
    if mode == "replace":
        return incoming

    incoming_by_name = {
        str(server.get("name") or "").strip(): server
        for server in incoming
        if isinstance(server, dict) and str(server.get("name") or "").strip()
    }

    merged: List[Dict[str, Any]] = []
    used: set[str] = set()
    for server in existing_list:
        if not isinstance(server, dict):
            continue
        name = str(server.get("name") or "").strip()
        if name and name in incoming_by_name:
            merged.append(deepcopy(incoming_by_name[name]))
            used.add(name)
        else:
            merged.append(deepcopy(server))

    for server in incoming:
        name = str(server.get("name") or "").strip()
        if name and name in used:
            continue
        merged.append(deepcopy(server))
        if name:
            used.add(name)
    return merged


def _normalize_source_format(source_format: str | None, source: str | None) -> str:
    value = str(source_format or "").strip().lower()
    if value in {"json", "yaml", "yml"}:
        return "yaml" if value == "yml" else value
    source_text = str(source or "").strip().lower()
    if source_text.endswith((".yaml", ".yml")):
        return "yaml"
    if source_text.endswith((".json", ".mcp")):
        return "json"
    return "auto"


def _extract_server_collection(payload: Any) -> tuple[Any, str, List[str]]:
    if isinstance(payload, list):
        return payload, "array", []
    if not isinstance(payload, dict):
        return None, "unsupported", ["MCP import root must be an object or list"]

    for key, shape in (
        ("mcpServers", "claude_mcpServers"),
        ("mcp_servers", "project_mcp_servers"),
        ("servers", "generic_servers"),
    ):
        if key in payload:
            return payload.get(key), shape, []

    return None, "unknown", [
        "MCP import object must contain mcpServers, mcp_servers, or servers"
    ]


def _normalize_imported_server(
    raw_server: Dict[str, Any],
    *,
    name_hint: str,
) -> Dict[str, Any] | None:
    name = str(raw_server.get("name") or name_hint or "").strip()
    if not name or name.isdigit():
        return None

    url = str(raw_server.get("url") or raw_server.get("endpoint") or "").strip()
    command = str(raw_server.get("command") or raw_server.get("cmd") or "").strip()
    transport = _normalize_transport(
        raw_server.get("transport") or raw_server.get("type"),
        url=url,
        command=command,
    )

    server: Dict[str, Any] = {
        "name": name,
        "command": command,
        "args": _normalize_args(raw_server.get("args", [])),
        "env": _normalize_env(raw_server.get("env", {})),
        "cwd": str(raw_server.get("cwd") or raw_server.get("workingDirectory") or "").strip(),
        "enabled": _normalize_enabled(raw_server),
        "description": str(raw_server.get("description") or "").strip(),
        "transport": transport,
    }
    if url:
        server["url"] = url
    return server


def _normalize_args(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _normalize_env(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _normalize_enabled(raw_server: Dict[str, Any]) -> bool:
    if "disabled" in raw_server:
        return not _as_bool(raw_server.get("disabled"))
    if "enabled" in raw_server:
        return _as_bool(raw_server.get("enabled"))
    return True


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_transport(value: Any, *, url: str, command: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "local": "stdio",
        "stdio": "stdio",
        "sse": "sse",
        "http": "http",
        "https": "http",
        "streamablehttp": "streamable_http",
        "streamable_http": "streamable_http",
    }
    if text in aliases:
        return aliases[text]
    if url:
        return "sse" if "/sse" in url.lower() else "streamable_http"
    if command:
        return "stdio"
    return "stdio"
