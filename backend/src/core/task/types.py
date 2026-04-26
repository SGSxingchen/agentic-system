"""Task 抽象的类型定义（v2 Phase B 支柱 2 + 支柱 5）

TaskState 是异步工作的统一表示：包含状态机、进度、结果、磁盘 transcript 引用。
现阶段唯一的 TaskType 是 PIPELINE；未来 Phase C 起会扩展 SUB_AGENT、SHELL。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class TaskType(str, Enum):
    """Task 类型枚举"""

    PIPELINE = "pipeline"
    # 预留：未来 Phase C/D 实装
    # SUB_AGENT = "sub_agent"
    # SHELL = "shell"


class TaskStatus(str, Enum):
    """Task 生命周期状态机

    pending → running → {completed | failed | killed}
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class AgentProgress:
    """Task 运行时增量进度

    由编排层（Pipeline / Agent loop）增量上报，
    供 TaskRegistry 累计 + WebSocket / API 暴露给前端。
    """

    tool_count: int = 0
    total_tokens: int = 0
    activity: str = ""
    last_tool: Optional[str] = None
    current_step: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class TaskState:
    """单个异步任务的状态快照

    生命周期由 TaskRegistry 维护；transcript 增量写入 output_file。
    """

    id: str
    type: TaskType
    requirement: str
    pipeline_name: str
    status: TaskStatus = TaskStatus.PENDING
    progress: AgentProgress = field(default_factory=AgentProgress)
    error: Optional[str] = None

    # 兼容旧 routes/tasks.py 的中间结果字段
    plan: Optional[Any] = None
    code: Optional[Any] = None
    review: Optional[Any] = None
    output: Optional[Any] = None

    # 时序
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    ended_at: Optional[str] = None

    # 副产物
    output_file: Optional[str] = None
    parent_id: Optional[str] = None

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为前端友好的字典（枚举 → 字符串）"""
        return {
            "task_id": self.id,
            "id": self.id,  # 保持向后兼容
            "type": self.type.value,
            "status": self.status.value,
            "requirement": self.requirement,
            "pipeline": self.pipeline_name,
            "progress": self.progress.to_dict(),
            "error": self.error,
            "plan": self.plan,
            "code": self.code,
            "review": self.review,
            "output": self.output,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ended_at": self.ended_at,
            "output_file": self.output_file,
            "parent_id": self.parent_id,
        }
