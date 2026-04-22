"""扳机定义 - 将事件与 Agent 关联的触发器

Trigger 描述了当某种事件发生时，应该由哪个 Agent 响应，
以及可选的条件过滤和优先级排序。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Trigger:
    """事件扳机

    Attributes:
        id: 扳机唯一标识
        event_type: 监听的事件类型（如 "code_generated"）
        agent_name: 响应该事件的 Agent 名称
        condition: 可选的 Python 表达式条件，用事件 data 作为局部变量求值
        priority: 优先级，数值越小越先执行（0 最高）
        async_mode: 是否以异步方式执行（True = 不阻塞后续扳机）
        enabled: 是否启用
    """
    id: str
    event_type: str
    agent_name: str
    condition: Optional[str] = None
    priority: int = 0
    async_mode: bool = True
    enabled: bool = True
