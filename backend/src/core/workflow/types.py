"""工作流类型定义"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(str, Enum):
    """工作流 / 任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    """工作流中的单个任务

    Attributes:
        name: 任务名称（唯一标识）
        agent: 负责执行的 Agent 名称
        input_data: 输入数据，支持 ${variable} 引用上游输出
        output_key: 输出键名，执行结果保存到工作流上下文中的 key
        condition: 条件表达式（Python），为空表示无条件执行
        max_iterations: 最大迭代次数（用于修复循环等场景），0 表示不限制
        timeout: 超时（秒），None 表示不限
    """
    name: str
    agent: str
    input_data: Optional[Dict[str, Any]] = None
    output_key: Optional[str] = None
    condition: Optional[str] = None
    max_iterations: int = 1
    timeout: Optional[float] = None


@dataclass
class TaskResult:
    """单个任务的执行结果"""
    task_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    iterations: int = 0
    duration_ms: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class WorkflowResult:
    """工作流整体执行结果"""
    status: WorkflowStatus = WorkflowStatus.PENDING
    task_results: List[TaskResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "task_results": [
                {
                    "task_name": tr.task_name,
                    "status": tr.status.value,
                    "output": tr.output,
                    "error": tr.error,
                    "iterations": tr.iterations,
                    "duration_ms": round(tr.duration_ms, 2),
                }
                for tr in self.task_results
            ],
            "context": self.context,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }
