"""Pipeline 类型定义"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class PipelineStatus(Enum):
    """管线/步骤执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStep:
    """管线步骤定义

    Attributes:
        name: 步骤名称
        capability: 要调用的能力名称（Agent 或工具）
        input_data: 输入数据，支持 ${variable} 引用上下文
        output_key: 输出键名，结果存入管线上下文
        condition: 可选条件表达式（Python），为空则无条件执行
        max_retries: 最大重试次数（默认 1，即不重试）
        timeout: 超时秒数（可选）
    """

    name: str
    capability: str
    input_data: Optional[Dict[str, Any]] = None
    output_key: Optional[str] = None
    condition: Optional[str] = None
    max_retries: int = 1
    timeout: Optional[float] = None


@dataclass
class StepResult:
    """步骤执行结果"""

    step_name: str
    status: PipelineStatus = PipelineStatus.PENDING
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retries: int = 0
    duration_ms: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class PipelineConfig:
    """管线配置"""

    name: str
    description: str = ""
    mode: str = "sequential"  # "sequential" | "parallel"
    steps: List[PipelineStep] = field(default_factory=list)


@dataclass
class PipelineResult:
    """管线执行结果"""

    status: PipelineStatus = PipelineStatus.PENDING
    step_results: List[StepResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
