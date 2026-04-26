"""Agent 系统

导出:
- Agent              — 通用配置化 Agent（行为由 YAML 驱动 + 内置工具循环）
- AgentStatus        — 状态枚举 (IDLE, BUSY, ERROR, STOPPED)
- AgentMetadata      — 元数据数据类
- AgentRegistry      — Agent 注册表
- AgentLifecycleManager — 生命周期管理器
"""
from .agent import Agent, AgentStatus, AgentMetadata
from .registry import AgentRegistry
from .lifecycle import AgentLifecycleManager

__all__ = [
    "Agent",
    "AgentStatus",
    "AgentMetadata",
    "AgentRegistry",
    "AgentLifecycleManager",
]
