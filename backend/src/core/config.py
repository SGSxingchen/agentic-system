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
    max_retries: int = Field(default=3, ge=0, description="LLM 调用瞬态错误最大重试次数（不含首发）")
    retry_initial_delay: float = Field(default=1.0, ge=0, description="首次重试退避秒数；之后 ×2 + ±20% jitter")
    openai: Dict[str, Any] = Field(default_factory=dict, description="OpenAI 专属对话参数")
    anthropic: Dict[str, Any] = Field(default_factory=dict, description="Anthropic 专属对话参数")


class MemoryConfig(BaseModel):
    """记忆系统配置。"""

    backend: str = Field(default="chroma", description="存储后端: memory, chroma")
    persist_dir: str = Field(default="./data/chroma", description="持久化目录")
    collection_name: str = Field(default="agent_memories", description="集合名称")
    auto_reflection_enabled: bool = Field(default=True, description="是否启用自动对话反思形成记忆")
    reflection_min_turns: int = Field(default=3, ge=1, description="自动反思触发轮数")
    reflection_max_messages: int = Field(default=12, ge=2, description="反思窗口最大消息数")
    recall_max_results: int = Field(default=3, ge=1, description="默认注入提示词的召回记忆数量")
    recall_max_chars: int = Field(default=1200, ge=200, description="默认注入提示词的召回上下文字符预算")
    recall_score_threshold: float = Field(default=0.0, ge=0, le=1, description="召回结果最低综合分数阈值")
    fallback_to_memory_on_error: bool = Field(default=True, description="Chroma 初始化失败时是否降级内存")
    consolidation_threshold: float = Field(default=0.3, ge=0, le=1, description="记忆巩固相似阈值")
    forget_after_days: int = Field(default=1, ge=1, description="多少天未访问后进入遗忘候选")
    forget_min_importance: float = Field(default=0.3, ge=0, le=1, description="遗忘的低重要性阈值")


class BusConfig(BaseModel):
    """消息总线配置。"""

    queue_size: int = Field(default=1000, description="消息队列大小")
    history_size: int = Field(default=500, description="消息历史保留数量")


class ServerConfig(BaseModel):
    """FastAPI 服务器配置 (含 A11 全局密码门禁)。"""

    host: str = Field(default="127.0.0.1", description="服务器绑定地址")
    port: int = Field(default=8001, ge=1, le=65535, description="服务器端口")
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
        ],
        description="允许的前端来源",
    )
    # A11: 公网部署密码门禁 — 空字符串等于不开启门禁。
    access_password: str = Field(
        default="",
        description="A11 全局访问密码；空字符串等于不开启门禁",
    )
    failed_login_max_attempts: int = Field(
        default=5,
        ge=1,
        description="同一 IP 在锁定窗口内允许的最大失败次数",
    )
    failed_login_lockout_seconds: int = Field(
        default=60,
        ge=1,
        description="失败计数滑动窗口长度（秒）",
    )


class ContextConfig(BaseModel):
    """上下文管理配置。"""

    persist_dir: str = Field(default="./data/context", description="上下文持久化目录")


class AgentConfig(BaseModel):
    """单个智能体配置。"""

    name: str = Field(description="智能体名称")
    type: str = Field(default="builtin", description="智能体类型")
    description: str = Field(default="", description="智能体描述")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    skills: Dict[str, Any] = Field(default_factory=dict, description="该 Agent 专属 skills 配置")
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list, description="该 Agent 专属 MCP server 配置")
    config: Dict[str, Any] = Field(default_factory=dict, description="智能体私有配置")


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

    workspace_root: str = Field(default="./workspace", description="Workspace root for file/shell tools")
    enforce_workspace_boundary: bool = Field(
        default=False,
        description=(
            "是否强制文件/Shell 工具的工作区边界。默认 False：相对路径仍落到工作区根，"
            "但绝对路径/越界路径放行（便于读取附件等工作区外文件）。设 True 恢复严格沙箱。"
        ),
    )


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


class AgentCreationConfig(BaseModel):
    """A4: Agent 创建/更新时的工具黑名单配置（escape hatch）。

    HIGH_RISK_TOOLS 默认放开后，部署方仍可通过 ``forbidden_tools`` 显式锁
    住特定工具。空列表表示"全放开"。
    """

    model_config = ConfigDict(extra="allow")

    forbidden_tools: List[str] = Field(default_factory=list)


class DispatchConfig(BaseModel):
    """A10 Plan Task 11: dispatch_agent 嵌套深度配置。

    默认 5（之前硬编码 1，几乎禁止嵌套派生）。部署方可通过 system.yaml
    ``dispatch.max_depth`` 调整。
    """

    model_config = ConfigDict(extra="allow")

    max_depth: int = Field(default=5, ge=1, description="dispatch_agent 最大嵌套深度")


class AgentDefaultsConfig(BaseModel):
    """A23.2: Agent 全局默认值。

    单 Agent yaml 未显式声明字段时回退到这里。当前仅暴露 ``token_budget``，
    后续如需统一其它 Agent 默认值（max_iterations / nudge 阈值等）可继续扩展。
    """

    model_config = ConfigDict(extra="allow")

    token_budget: int = Field(
        default=300000,
        ge=1000,
        description="单次 Agent 调用累计 token 预算上限（默认 300000）。Agent yaml 字段优先。",
    )


class SystemConfig(BaseModel):
    """顶层系统配置。"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    bus: BusConfig = Field(default_factory=BusConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agents: List[AgentConfig] = Field(default_factory=list)
    agent_creation: AgentCreationConfig = Field(default_factory=AgentCreationConfig)
    dispatch: DispatchConfig = Field(default_factory=DispatchConfig)
    agent_defaults: AgentDefaultsConfig = Field(default_factory=AgentDefaultsConfig)


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
    if value := os.getenv("MEMORY_FALLBACK_TO_MEMORY_ON_ERROR"):
        memory["fallback_to_memory_on_error"] = value.strip().lower() in {"1", "true", "yes", "on"}
    if value := os.getenv("MEMORY_AUTO_REFLECTION_ENABLED"):
        memory["auto_reflection_enabled"] = value.strip().lower() in {"1", "true", "yes", "on"}
    if value := os.getenv("MEMORY_RECALL_MAX_RESULTS"):
        memory["recall_max_results"] = int(value)
    if value := os.getenv("MEMORY_RECALL_SCORE_THRESHOLD"):
        memory["recall_score_threshold"] = float(value)

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
    if value := os.getenv("AGENTIC_ENFORCE_WORKSPACE_BOUNDARY"):
        file_tools["enforce_workspace_boundary"] = value.strip().lower() in {"1", "true", "yes", "on"}

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


_system_config_cache: Optional[SystemConfig] = None


def get_system_config(*, refresh: bool = False) -> SystemConfig:
    """A11: 进程级缓存 SystemConfig，供中间件等热路径复用。

    middleware 在每次请求都会读 ``server.access_password``，避免重复 IO。
    需要热重载时调用 ``get_system_config(refresh=True)`` 或 ``clear_system_config_cache()``。
    """

    global _system_config_cache
    if refresh or _system_config_cache is None:
        _system_config_cache = load_system_config()
    return _system_config_cache


def clear_system_config_cache() -> None:
    """清空 ``get_system_config`` 缓存。配置 yaml 改动后应调用一次。"""

    global _system_config_cache
    _system_config_cache = None


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
        },
        "memory": {
            "backend": "chroma",
            "persist_dir": "./data/chroma",
            "collection_name": "agent_memories",
            "auto_reflection_enabled": True,
            "reflection_min_turns": 3,
            "reflection_max_messages": 12,
            "recall_max_results": 3,
            "recall_max_chars": 1200,
            "recall_score_threshold": 0.0,
            "fallback_to_memory_on_error": True,
            "consolidation_threshold": 0.3,
            "forget_after_days": 1,
            "forget_min_importance": 0.3,
        },
        "tools": {
            "web_search": {
                "provider": "duckduckgo",
                "base_url": "",
                "api_key": "",
                "max_results": 5,
                "timeout": 10,
            },
            "web_fetch": {
                "timeout": 10,
                "max_chars": 4000,
            },
            "file": {
                "workspace_root": "./workspace",
            },
            "shell": {
                "enabled": False,
                "timeout": 30,
            },
            "custom": {},
        },
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
