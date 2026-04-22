"""Agent 系统

导出:
- Agent              — 通用配置化 Agent（推荐使用）
- AgentStatus        — 状态枚举 (IDLE, BUSY, ERROR, STOPPED)
- AgentMetadata      — 元数据数据类
- AgentRegistry      — Agent 注册表
- AgentLifecycleManager — 生命周期管理器
"""
from .agent import Agent, AgentStatus, AgentMetadata
from .registry import AgentRegistry
from .lifecycle import AgentLifecycleManager

# 向后兼容：BaseAgent 作为 Agent 的别名
BaseAgent = Agent

__all__ = [
    "Agent",
    "BaseAgent",
    "AgentStatus",
    "AgentMetadata",
    "AgentRegistry",
    "AgentLifecycleManager",
]
