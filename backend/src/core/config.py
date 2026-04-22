"""配置管理 - Pydantic 类型安全配置

支持:
- 从 YAML 文件加载
- config/ 目录多文件 YAML 合并加载
- 环境变量覆盖
- 类型校验和默认值
- load_config() 向后兼容
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─── 配置模型 ──────────────────────────────────────────────


class LLMConfig(BaseModel):
    """LLM 提供商配置"""
    provider: str = Field(default="openai", description="LLM 提供商: openai, anthropic")
    api_key: str = Field(default="", description="API Key")
    model: str = Field(default="gpt-3.5-turbo", description="模型名称")
    base_url: str = Field(default="", description="自定义 API 地址")
    temperature: float = Field(default=0.7, description="采样温度")
    max_tokens: int = Field(default=4096, description="最大输出 token 数")


class MemoryConfig(BaseModel):
    """记忆系统配置"""
    backend: str = Field(default="memory", description="存储后端: memory, chroma")
    persist_dir: str = Field(default="./data/chroma", description="持久化目录")
    collection_name: str = Field(default="agent_memories", description="集合名称")


class BusConfig(BaseModel):
    """消息总线配置"""
    queue_size: int = Field(default=1000, description="消息队列大小，0 为无限")
    history_size: int = Field(default=500, description="消息历史保留数量")


class ContextConfig(BaseModel):
    """上下文管理配置"""
    persist_dir: str = Field(default="./data/context", description="项目上下文持久化目录")


class AgentConfig(BaseModel):
    """单个智能体配置"""
    name: str = Field(description="智能体名称")
    type: str = Field(default="builtin", description="智能体类型")
    description: str = Field(default="", description="智能体描述")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    config: Dict[str, Any] = Field(default_factory=dict, description="智能体私有配置")


class WorkflowConfig(BaseModel):
    """工作流配置"""
    max_iterations: int = Field(default=10, description="全局最大迭代次数")
    default_timeout: float = Field(default=300.0, description="默认超时（秒）")


class SystemConfig(BaseModel):
    """顶层系统配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    bus: BusConfig = Field(default_factory=BusConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    agents: List[AgentConfig] = Field(default_factory=list)


# ─── 加载逻辑 ──────────────────────────────────────────────


def _load_yaml(config_path: Path) -> Dict[str, Any]:
    """从 YAML 文件加载原始 dict"""
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个字典，override 覆盖 base

    - 两边都是 dict → 递归合并
    - 否则 → override 覆盖 base
    """
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    """环境变量覆盖

    支持以下环境变量:
    - LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
    - MEMORY_BACKEND, MEMORY_PERSIST_DIR
    - BUS_QUEUE_SIZE, BUS_HISTORY_SIZE
    """
    llm = raw.setdefault("llm", {})
    if v := os.getenv("LLM_PROVIDER"):
        llm["provider"] = v
    if v := (os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        llm["api_key"] = v
    if v := os.getenv("LLM_MODEL"):
        llm["model"] = v
    if v := (os.getenv("LLM_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")):
        llm["base_url"] = v

    memory = raw.setdefault("memory", {})
    if v := os.getenv("MEMORY_BACKEND"):
        memory["backend"] = v
    if v := os.getenv("MEMORY_PERSIST_DIR"):
        memory["persist_dir"] = v

    bus = raw.setdefault("bus", {})
    if v := os.getenv("BUS_QUEUE_SIZE"):
        bus["queue_size"] = int(v)
    if v := os.getenv("BUS_HISTORY_SIZE"):
        bus["history_size"] = int(v)

    return raw


def load_yaml_configs(config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """加载 config/ 目录下所有 YAML 文件并合并为一个配置字典

    每个 YAML 文件的内容按文件名（去掉扩展名）作为顶层键合并。
    特殊处理:
    - system.yaml: 其内容直接合并到顶层（包含 llm, bus, memory 等全局配置）
    - agents.yaml: 提取其 agents 列表
    - triggers.yaml: 提取其 triggers 列表
    - workflows.yaml: 提取其 workflows 字典
    - capabilities.yaml: 提取其 capabilities 列表

    Args:
        config_dir: config/ 目录路径。默认自动搜索项目根目录下的 config/

    Returns:
        合并后的配置字典
    """
    if config_dir is None:
        # 从 backend/src/core/config.py 向上找到项目根目录
        project_root = Path(__file__).parent.parent.parent.parent
        config_dir = project_root / "config"

    if not config_dir.is_dir():
        return {}

    merged: Dict[str, Any] = {}

    for yaml_file in sorted(config_dir.glob("*.yaml")):
        data = _load_yaml(yaml_file)
        if not data:
            continue

        stem = yaml_file.stem  # 文件名（去掉 .yaml）

        if stem == "system":
            # system.yaml 的内容直接合并到顶层（llm, bus, memory 等）
            merged = _deep_merge(merged, data)
        else:
            # 其他文件: 用文件名作为键，或者提取同名顶层键
            # 例如 agents.yaml 含 {agents: [...]} → 取 agents 列表
            if stem in data:
                merged[stem] = data[stem]
            else:
                merged[stem] = data

        logger.debug(f"Loaded config from {yaml_file.name}")

    return merged


def load_system_config(config_path: Optional[Path] = None) -> SystemConfig:
    """加载完整的类型安全配置

    Args:
        config_path: YAML 配置文件路径。默认为 src/config.yaml

    Returns:
        SystemConfig 实例
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    raw = _load_yaml(config_path)
    raw = _apply_env_overrides(raw)
    return SystemConfig(**raw)


def load_single_yaml(filename: str, config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """读取 config/ 目录下的单个 YAML 文件

    Args:
        filename: 文件名，如 "agents.yaml"
        config_dir: config/ 目录路径，默认自动搜索

    Returns:
        YAML 内容的原始 dict
    """
    if config_dir is None:
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
    return _load_yaml(config_dir / filename)


def save_yaml_config(filename: str, data: Dict[str, Any], config_dir: Optional[Path] = None) -> None:
    """将数据写入 config/ 目录下的 YAML 文件

    Args:
        filename: 文件名，如 "agents.yaml"
        data: 要写入的数据
        config_dir: config/ 目录路径，默认自动搜索
    """
    if config_dir is None:
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    filepath = config_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info(f"Saved config to {filepath}")


def load_config() -> Dict[str, Any]:
    """向后兼容的配置加载函数

    返回原始 dict 格式，与旧代码兼容。
    新代码请使用 load_system_config()。
    """
    config_path = Path(__file__).parent.parent / "config.yaml"

    if not config_path.exists():
        return {
            "llm": {
                "provider": "openai",
                "api_key": os.getenv("OPENAI_API_KEY", ""),
                "model": os.getenv("LLM_MODEL", "gpt-3.5-turbo"),
            }
        }

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
