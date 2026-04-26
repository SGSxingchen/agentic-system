"""Task 抽象（v2 Phase B 支柱 2 + 支柱 5）

导出:
- TaskState / TaskStatus / TaskType — 数据类与枚举
- AgentProgress — 增量进度
- TaskRegistry — 注册中心
- TranscriptWriter / read_transcript / transcript_path — 磁盘 transcript
"""
from .types import AgentProgress, TaskState, TaskStatus, TaskType
from .registry import TaskRegistry
from .transcript import TranscriptWriter, read_transcript, transcript_path

__all__ = [
    "AgentProgress",
    "TaskState",
    "TaskStatus",
    "TaskType",
    "TaskRegistry",
    "TranscriptWriter",
    "read_transcript",
    "transcript_path",
]
