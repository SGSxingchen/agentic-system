"""配置与健康检查路由

端点:
- GET  /api/config   — 获取配置（隐藏 api_key）
- POST /api/config   — 更新配置并热重载
- GET  /api/health   — 健康检查
"""
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
import yaml

from ..schemas import APIResponse, ConfigUpdateRequest
from ..dependencies import (
    get_bus,
    get_agent_registry,
    get_memory_store,
    get_capability_registry,
    reload_agent_fn,
)

router = APIRouter(tags=["config"])

SENSITIVE_CONFIG_KEYS = {
    "api_key",
    "apikey",
    "apiKey",
    "token",
    "access_token",
    "secret",
    "password",
    "authorization",
}


def _runtime_config_path() -> Path:
    return Path(__file__).parent.parent.parent / "config.yaml"


def _load_runtime_config() -> Dict[str, Any]:
    path = _runtime_config_path()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().replace("-", "_").lower()
    return normalized in SENSITIVE_CONFIG_KEYS


def _safe_extra_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, value in data.items():
        if _is_sensitive_key(str(key)):
            continue
        safe[key] = _safe_extra_dict(value) if isinstance(value, dict) else value
    return safe


def _safe_custom_tool_extra(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: _safe_extra_dict(value) if isinstance(value, dict) else value
        for key, value in config.items()
        if key not in {"enabled", "base_url", "api_key", "extra"} and not _is_sensitive_key(key)
    }


def _custom_tools_response(config: Dict[str, Any]) -> Dict[str, Any]:
    custom_tools = config.get("custom", {})
    if not isinstance(custom_tools, dict):
        return {}

    response: Dict[str, Any] = {}
    for name, item in custom_tools.items():
        if not isinstance(item, dict):
            continue
        extra = item.get("extra")
        response[str(name)] = {
            "enabled": bool(item.get("enabled", True)),
            "base_url": item.get("base_url", ""),
            "api_key_set": bool(item.get("api_key", "")),
            "extra": _safe_extra_dict(extra) if isinstance(extra, dict) else _safe_custom_tool_extra(item),
        }
    return response


def _preserve_blank_secret(target: Dict[str, Any], existing: Dict[str, Any], key: str = "api_key") -> None:
    if target.get(key):
        return

    previous = existing.get(key) if isinstance(existing, dict) else None
    if previous:
        target[key] = previous
    else:
        target.pop(key, None)


def _tools_response(config: Dict[str, Any]) -> Dict[str, Any]:
    tools = config.get("tools", {})
    web_search = tools.get("web_search", {})
    web_fetch = tools.get("web_fetch", {})
    file_tools = tools.get("file", {})
    shell = tools.get("shell", {})
    return {
        "web_search": {
            "provider": web_search.get("provider", "duckduckgo"),
            "base_url": web_search.get("base_url", ""),
            "api_key_set": bool(web_search.get("api_key", "")),
            "max_results": int(web_search.get("max_results", 5) or 5),
            "timeout": float(web_search.get("timeout", 10) or 10),
        },
        "web_fetch": {
            "timeout": float(web_fetch.get("timeout", 10) or 10),
            "max_chars": int(web_fetch.get("max_chars", 4000) or 4000),
        },
        "file": {
            "workspace_root": file_tools.get("workspace_root", ""),
        },
        "shell": {
            "enabled": bool(shell.get("enabled", False)),
            "timeout": float(shell.get("timeout", 30) or 30),
        },
        "custom": _custom_tools_response(tools),
    }


def _llm_response(config: Dict[str, Any]) -> Dict[str, Any]:
    llm = config.get("llm", {})
    openai = llm.get("openai", {})
    anthropic = llm.get("anthropic", {})
    return {
        "provider": llm.get("provider", "openai"),
        "model": llm.get("model", ""),
        "api_key_set": bool(llm.get("api_key")),
        "base_url": llm.get("base_url", ""),
        "temperature": llm.get("temperature", 0.7),
        "top_p": llm.get("top_p"),
        "max_tokens": int(llm.get("max_tokens", 4096) or 4096),
        "stop_sequences": llm.get("stop_sequences", []) if isinstance(llm.get("stop_sequences"), list) else [],
        "openai": openai if isinstance(openai, dict) else {},
        "anthropic": anthropic if isinstance(anthropic, dict) else {},
    }


@router.get("/api/config", response_model=APIResponse)
async def get_config():
    """获取配置（不暴露 api_key）"""
    from core.config import load_config

    config = load_config()
    return APIResponse(
        status="ok",
        data={
            "llm": _llm_response(config),
            "tools": _tools_response(config),
        },
    )


@router.post("/api/config", response_model=APIResponse)
async def update_config(config_data: ConfigUpdateRequest):
    """更新配置并热重载"""
    try:
        config_path = _runtime_config_path()
        existing = _load_runtime_config()
        existing_llm = existing.get("llm", {}) if isinstance(existing.get("llm"), dict) else {}
        existing_tools = existing.get("tools", {}) if isinstance(existing.get("tools"), dict) else {}

        llm = _deep_merge_dict(
            existing_llm,
            config_data.llm.model_dump(exclude_none=True),
        )
        _preserve_blank_secret(llm, existing_llm)

        config_dict = {
            **existing,
            "llm": llm,
        }

        if config_data.tools is not None:
            tools = config_data.tools.model_dump()
            existing_search = (
                existing_tools.get("web_search", {})
                if isinstance(existing_tools.get("web_search"), dict)
                else {}
            )
            _preserve_blank_secret(tools["web_search"], existing_search)

            existing_custom = (
                existing_tools.get("custom", {})
                if isinstance(existing_tools.get("custom"), dict)
                else {}
            )
            for name, custom_config in tools.get("custom", {}).items():
                previous_custom = (
                    existing_custom.get(name, {})
                    if isinstance(existing_custom.get(name), dict)
                    else {}
                )
                _preserve_blank_secret(custom_config, previous_custom)

            config_dict["tools"] = _deep_merge_dict(existing_tools, tools)

        config_path.write_text(
            yaml.dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        print(f"[OK] 配置已保存到: {config_path}")

        # 热重载 Agent
        reload = reload_agent_fn()
        if reload:
            await reload()

        return APIResponse(status="ok", message="配置已更新并重新加载")
    except Exception as e:
        print(f"[ERROR] 配置更新失败: {e}")
        import traceback

        traceback.print_exc()
        return APIResponse(status="error", message=str(e))


@router.get("/api/health", response_model=APIResponse)
async def health():
    """健康检查"""
    bus = get_bus()
    cap_registry = get_capability_registry()
    memory_store = get_memory_store()
    registry = get_agent_registry()

    return APIResponse(
        status="ok",
        data={
            "bus_running": bus._running if bus else False,
            "agent_loaded": cap_registry is not None and "assistant" in cap_registry,
            "memory_initialized": memory_store is not None,
            "agents_registered": len(registry) if registry else 0,
        },
    )
