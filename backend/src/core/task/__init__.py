"""Task 抽象（v2 Phase B 支柱 2 + 支柱 5；Phase C 加入 SUB_AGENT 与 contextvars）

导出:
- TaskState / TaskStatus / TaskType — 数据类与枚举（Phase C 加 SUB_AGENT）
- AgentProgress — 增量进度
- TaskRegistry — 注册中心（Phase C 支持 cascade kill 与 list_children）
- TranscriptWriter / read_transcript / transcript_path — 磁盘 transcript
- format_task_notification / make_user_message — Phase C `<task-notification>` 格式化
- get_/set_/reset_ parent_task_id / notification_box / workspace_root_override / dispatch_depth — Phase C contextvars
"""
from .types import AgentProgress, TaskState, TaskStatus, TaskType
from .registry import TaskRegistry
from .transcript import TranscriptWriter, read_transcript, transcript_path
from .notifications import format_task_notification, make_user_message
from .context import (
    get_parent_task_id,
    set_parent_task_id,
    reset_parent_task_id,
    get_notification_box,
    set_notification_box,
    reset_notification_box,
    get_workspace_root_override,
    set_workspace_root_override,
    reset_workspace_root_override,
    get_dispatch_depth,
    set_dispatch_depth,
    reset_dispatch_depth,
)

__all__ = [
    "AgentProgress",
    "TaskState",
    "TaskStatus",
    "TaskType",
    "TaskRegistry",
    "TranscriptWriter",
    "read_transcript",
    "transcript_path",
    "format_task_notification",
    "make_user_message",
    "get_parent_task_id",
    "set_parent_task_id",
    "reset_parent_task_id",
    "get_notification_box",
    "set_notification_box",
    "reset_notification_box",
    "get_workspace_root_override",
    "set_workspace_root_override",
    "reset_workspace_root_override",
    "get_dispatch_depth",
    "set_dispatch_depth",
    "reset_dispatch_depth",
]
