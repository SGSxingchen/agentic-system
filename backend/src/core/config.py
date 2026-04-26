"""配置管理。

支持:
- `config/*.yaml` 组件/系统配置加载
- `backend/src/config.yaml` 本地运行时配置加载
- 环境变量覆盖
- Pydantic 类型安全配置
- 兼容旧版 `load_config()` 调用方式
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class LLMConfig(BaseModel):
    """LLM 提供方配置。"""

    provider: str = Field(default="openai", description="LLM 提供方: openai, anthropic")
    api_key: str = Field(default="", description="API Key")
    model: str = Field(default="gpt-3.5-turbo", description="模型名称")
    base_url: str = Field(default="", description="自定义 API 地址")
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2, description="采样温度")
    top_p: Optional[float] = Field(default=None, ge=0, le=1, description="核采样概率")
    max_tokens: int = Field(default=4096, ge=1, description="最大输出 token 数")
    stop_sequences: List[str] = Field(default_factory=list, description="停止序列")
    openai: Dict[str, Any] = Field(default_factory=dict, description="OpenAI 专属对话参数")
    anthropic: Dict[str, Any] = Field(default_factory=dict, description="Anthropic 专属对话参数")


class MemoryConfig(BaseModel):
    """记忆系统配置。"""

    backend: str = Field(default="memory", description="存储后端: memory, chroma")
    persist_dir: str = Field(default="./data/chroma", description="持久化目录")
    collection_name: str = Field(default="agent_memories", description="集合名称")


class BusConfig(BaseModel):
    """消息总线配置。"""

    queue_size: int = Field(default=1000, description="消息队列大小")
    history_size: int = Field(default=500, description="消息历史保留数量")


class ContextConfig(BaseModel):
    """上下文管理配置。"""

    persist_dir: str = Field(default="./data/context", description="上下文持久化目录")


class AgentConfig(BaseModel):
    """单个智能体配置。"""

    name: str = Field(description="智能体名称")
    type: str = Field(default="builtin", description="智能体类型")
    description: str = Field(default="", description="智能体描述")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    config: Dict[str, Any] = Field(default_factory=dict, description="智能体私有配置")


class WorkflowConfig(BaseModel):
    """工作流配置。"""

    max_iterations: int = Field(default=10, description="全局最大迭代次数")
    default_timeout: float = Field(default=300.0, description="默认超时秒数")


class WebSearchToolConfig(BaseModel):
    """Web search tool configuration."""

    provider: str = Field(default="duckduckgo", description="duckduckgo | brave | serper")
    base_url: str = Field(default="", description="Optional provider API/search URL")
    api_key: str = Field(default="", description="Provider API key")
    max_results: int = Field(default=5, ge=1, le=10)
    timeout: float = Field(default=10, gt=0)


class WebFetchToolConfig(BaseModel):
    """Web fetch tool configuration."""

    timeout: float = Field(default=10, gt=0)
    max_chars: int = Field(default=4000, ge=200, le=20000)


class FileToolConfig(BaseModel):
    """Workspace file tool configuration."""

    workspace_root: str = Field(default="", description="Optional workspace root override")


class ShellToolConfig(BaseModel):
    """Shell tool configuration."""

    enabled: bool = Field(default=False)
    timeout: float = Field(default=30, gt=0)


class ToolsConfig(BaseModel):
    """Tool runtime configuration."""

    model_config = ConfigDict(extra="allow")

    web_search: WebSearchToolConfig = Field(default_factory=WebSearchToolConfig)
    web_fetch: WebFetchToolConfig = Field(default_factory=WebFetchToolConfig)
    file: FileToolConfig = Field(default_factory=FileToolConfig)
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    custom: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class SystemConfig(BaseModel):
    """顶层系统配置。"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    bus: BusConfig = Field(default_factory=BusConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agents: List[AgentConfig] = Field(default_factory=list)


def _default_project_root() -> Path:
    """返回项目根目录。"""

    return Path(__file__).resolve().parent.parent.parent.parent


def _default_runtime_config_path() -> Path:
    """返回运行时配置文件路径。"""

    return Path(__file__).resolve().parent.parent / "config.yaml"


def _load_yaml(config_path: Path) -> Dict[str, Any]:
    """从 YAML 文件加载原始 dict。"""

    if not config_path.exists():
        return {}

    with open(config_path, encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if isinstance(data, dict):
        return data

    return {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个字典，override 覆盖 base。"""

    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    """环境变量覆盖。"""

    llm = raw.setdefault("llm", {})
    if value := os.getenv("LLM_PROVIDER"):
        llm["provider"] = value
    if value := (os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        llm["api_key"] = value
    if value := os.getenv("LLM_MODEL"):
        llm["model"] = value
    if value := (os.getenv("LLM_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")):
        llm["base_url"] = value
    if value := os.getenv("LLM_TEMPERATURE"):
        llm["temperature"] = float(value)
    if value := os.getenv("LLM_TOP_P"):
        llm["top_p"] = float(value)
    if value := os.getenv("LLM_MAX_TOKENS"):
        llm["max_tokens"] = int(value)
    if value := os.getenv("LLM_STOP_SEQUENCES"):
        llm["stop_sequences"] = [item.strip() for item in value.split(",") if item.strip()]

    openai = llm.setdefault("openai", {})
    if value := os.getenv("OPENAI_MAX_COMPLETION_TOKENS"):
        openai["max_completion_tokens"] = int(value)
    if value := os.getenv("OPENAI_USE_LEGACY_MAX_TOKENS"):
        openai["use_legacy_max_tokens"] = value.strip().lower() in {"1", "true", "yes", "on"}
    if value := os.getenv("OPENAI_PRESENCE_PENALTY"):
        openai["presence_penalty"] = float(value)
    if value := os.getenv("OPENAI_FREQUENCY_PENALTY"):
        openai["frequency_penalty"] = float(value)
    if value := os.getenv("OPENAI_REASONING_EFFORT"):
        openai["reasoning_effort"] = value
    if value := os.getenv("OPENAI_SEED"):
        openai["seed"] = int(value)

    anthropic = llm.setdefault("anthropic", {})
    if value := os.getenv("ANTHROPIC_TOP_K"):
        anthropic["top_k"] = int(value)

    memory = raw.setdefault("memory", {})
    if value := os.getenv("MEMORY_BACKEND"):
        memory["backend"] = value
    if value := os.getenv("MEMORY_PERSIST_DIR"):
        memory["persist_dir"] = value

    bus = raw.setdefault("bus", {})
    if value := os.getenv("BUS_QUEUE_SIZE"):
        bus["queue_size"] = int(value)
    if value := os.getenv("BUS_HISTORY_SIZE"):
        bus["history_size"] = int(value)

    tools = raw.setdefault("tools", {})

    web_search = tools.setdefault("web_search", {})
    if value := os.getenv("WEB_SEARCH_PROVIDER"):
        web_search["provider"] = value
    if value := os.getenv("WEB_SEARCH_BASE_URL"):
        web_search["base_url"] = value
    if value := os.getenv("WEB_SEARCH_API_KEY"):
        web_search["api_key"] = value
    if value := os.getenv("WEB_SEARCH_MAX_RESULTS"):
        web_search["max_results"] = int(value)
    if value := os.getenv("WEB_SEARCH_TIMEOUT"):
        web_search["timeout"] = float(value)

    web_fetch = tools.setdefault("web_fetch", {})
    if value := os.getenv("WEB_FETCH_TIMEOUT"):
        web_fetch["timeout"] = float(value)
    if value := os.getenv("WEB_FETCH_MAX_CHARS"):
        web_fetch["max_chars"] = int(value)

    file_tools = tools.setdefault("file", {})
    if value := os.getenv("AGENTIC_WORKSPACE_ROOT"):
        file_tools["workspace_root"] = value

    shell = tools.setdefault("shell", {})
    if value := os.getenv("ENABLE_SHELL_TOOL"):
        shell["enabled"] = value.strip().lower() in {"1", "true", "yes", "on"}
    if value := os.getenv("SHELL_TOOL_TIMEOUT"):
        shell["timeout"] = float(value)

    return raw


def load_yaml_configs(config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """加载 `config/` 目录下所有 YAML 文件并按约定合并。"""

    if config_dir is None:
        config_dir = _default_project_root() / "config"

    if not config_dir.is_dir():
        return {}

    merged: Dict[str, Any] = {}

    for yaml_file in sorted(config_dir.glob("*.yaml")):
        data = _load_yaml(yaml_file)
        if not data:
            continue

        stem = yaml_file.stem
        if stem == "system":
            merged = _deep_merge(merged, data)
        else:
            if stem in data:
                merged[stem] = data[stem]
            else:
                merged[stem] = data

        logger.debug("Loaded config from %s", yaml_file.name)

    return merged


def load_system_config(config_path: Optional[Path] = None) -> SystemConfig:
    """加载类型安全配置。"""

    if config_path is None:
        raw = load_config()
    else:
        raw = _load_yaml(config_path)
        raw = _apply_env_overrides(raw)

    return SystemConfig(**raw)


def load_single_yaml(filename: str, config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """读取 `config/` 目录下的单个 YAML 文件。"""

    if config_dir is None:
        config_dir = _default_project_root() / "config"
    return _load_yaml(config_dir / filename)


def save_yaml_config(
    filename: str,
    data: Dict[str, Any],
    config_dir: Optional[Path] = None,
) -> None:
    """将数据写入 `config/` 目录下的 YAML 文件。"""

    if config_dir is None:
        config_dir = _default_project_root() / "config"

    config_dir.mkdir(parents=True, exist_ok=True)
    filepath = config_dir / filename
    with open(filepath, "w", encoding="utf-8") as file:
        yaml.dump(
            data,
            file,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    logger.info("Saved config to %s", filepath)


def load_config(
    config_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """加载兼容旧版调用方式的原始 dict 配置。

    加载优先级:
    1. `config/*.yaml`
    2. `backend/src/config.yaml`
    3. 环境变量
    """

    merged: Dict[str, Any] = {
        "llm": {
            "provider": "openai",
            "api_key": "",
            "model": "gpt-3.5-turbo",
            "base_url": "",
        }
    }

    merged = _deep_merge(merged, load_yaml_configs(config_dir=config_dir))

    runtime_config_path = config_path or _default_runtime_config_path()
    if runtime_config_path.exists():
        merged = _deep_merge(merged, _load_yaml(runtime_config_path))

    merged = _apply_env_overrides(merged)

    llm = merged.setdefault("llm", {})
    if not llm.get("api_key"):
        llm["api_key"] = os.getenv("OPENAI_API_KEY", "")

    return merged


def get_tool_runtime_config(
    tool_name: str,
    config_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return merged runtime config for a tool.

    Known/native tools usually live at `tools.<tool_name>`. User-defined tool
    credentials from the settings UI live at `tools.custom.<tool_name>`.
    Top-level tool config wins if both are present.
    """

    tools = load_config(config_path=config_path, config_dir=config_dir).get("tools", {})
    if not isinstance(tools, dict):
        return {}

    custom_tools = tools.get("custom", {})
    custom = {}
    if isinstance(custom_tools, dict) and isinstance(custom_tools.get(tool_name), dict):
        custom = dict(custom_tools[tool_name])

    direct = tools.get(tool_name, {})
    if isinstance(direct, dict):
        return _deep_merge(custom, dict(direct))

    return custom
