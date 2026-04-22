"""能力系统 - 插件化能力架构"""
from .base import CapabilityBase, CapabilitySchema
from .registry import CapabilityRegistry

# AgentCapability 延迟导入，避免 agent ↔ capability 循环依赖
# 使用时: from core.capability.agent_adapter import AgentCapability

__all__ = [
    "CapabilityBase",
    "CapabilitySchema",
    "CapabilityRegistry",
]
