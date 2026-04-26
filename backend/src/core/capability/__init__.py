"""能力系统 - 插件化能力架构"""
from .base import CapabilityBase, CapabilitySchema
from .dynamic import DynamicToolCapability, load_dynamic_capabilities
from .prompt_override import (
    PromptOverrideCapability,
    apply_prompt_override,
    apply_prompt_overrides,
    unwrap_capability,
)
from .registry import CapabilityRegistry

# AgentCapability 延迟导入，避免 agent ↔ capability 循环依赖
# 使用时: from core.capability.agent_adapter import AgentCapability

__all__ = [
    "CapabilityBase",
    "CapabilitySchema",
    "DynamicToolCapability",
    "PromptOverrideCapability",
    "CapabilityRegistry",
    "apply_prompt_override",
    "apply_prompt_overrides",
    "load_dynamic_capabilities",
    "unwrap_capability",
]
