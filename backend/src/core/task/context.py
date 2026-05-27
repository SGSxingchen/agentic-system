"""Phase C 运行时上下文（ContextVars）

跨 async 调用栈传递的运行时状态：
- 当前父任务 task_id（dispatch_agent 用来给子 task 设 parent_id）
- 当前 Agent 的 notification 收件箱（dispatch_agent 完成时把结果塞回这里）
- 当前 worktree 工作根（_safety.get_workspace_root 优先读）
- 当前 dispatch 深度（防嵌套派生）

所有 setter 返回 contextvars.Token；调用方用 try/finally 配合 reset_* 还原。
ContextVars 在 asyncio.create_task / gather 中自动复制传递，不需要手动透传。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Dict, List, Optional


_parent_task_id_cv: ContextVar[Optional[str]] = ContextVar(
    "agentic_parent_task_id", default=None
)
_notification_box_cv: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "agentic_notification_box", default=None
)
_workspace_root_cv: ContextVar[Optional[Path]] = ContextVar(
    "agentic_workspace_root", default=None
)
_dispatch_depth_cv: ContextVar[int] = ContextVar(
    "agentic_dispatch_depth", default=0
)
_current_room_id_cv: ContextVar[Optional[str]] = ContextVar(
    "agentic_current_room_id", default=None
)
_current_speaker_name_cv: ContextVar[Optional[str]] = ContextVar(
    "agentic_current_speaker_name", default=None
)
# 单 task 内 chatroom_create_agent 计数器：用一个 list[int] 当可变容器，
# 每次创建 +1，便于工具内部读写而无需新建 Token。
_current_create_counter_cv: ContextVar[Optional[List[int]]] = ContextVar(
    "agentic_current_create_counter", default=None
)
# Spec 2 §5 / Task 9 — 当前发言任务的占位消息 id（chatroom_dispatch 在派发时
# 把它挂到 child speaking task 的 parent_message_id 上，以便 LM 能在 XML
# history 里追到 reply-thread 关系）。
_current_parent_message_id_cv: ContextVar[Optional[str]] = ContextVar(
    "agentic_current_parent_message_id", default=None
)


# ─── parent_task_id ────────────────────────────────────


def get_parent_task_id() -> Optional[str]:
    return _parent_task_id_cv.get()


def set_parent_task_id(task_id: Optional[str]) -> Token:
    return _parent_task_id_cv.set(task_id)


def reset_parent_task_id(token: Token) -> None:
    _parent_task_id_cv.reset(token)


# ─── notification_box ──────────────────────────────────


def get_notification_box() -> Optional[List[Dict[str, Any]]]:
    return _notification_box_cv.get()


def set_notification_box(box: Optional[List[Dict[str, Any]]]) -> Token:
    return _notification_box_cv.set(box)


def reset_notification_box(token: Token) -> None:
    _notification_box_cv.reset(token)


# ─── workspace_root（worktree 隔离）─────────────────────


def get_workspace_root_override() -> Optional[Path]:
    return _workspace_root_cv.get()


def set_workspace_root_override(root: Optional[Path]) -> Token:
    return _workspace_root_cv.set(root)


def reset_workspace_root_override(token: Token) -> None:
    _workspace_root_cv.reset(token)


# ─── dispatch_depth（防嵌套派生）────────────────────────


def get_dispatch_depth() -> int:
    return _dispatch_depth_cv.get()


def set_dispatch_depth(depth: int) -> Token:
    return _dispatch_depth_cv.set(depth)


def reset_dispatch_depth(token: Token) -> None:
    _dispatch_depth_cv.reset(token)


# ─── current_room_id（聊天室上下文）─────────────────────


def get_current_room_id() -> Optional[str]:
    return _current_room_id_cv.get()


def set_current_room_id(room_id: Optional[str]) -> Token:
    return _current_room_id_cv.set(room_id)


def reset_current_room_id(token: Token) -> None:
    _current_room_id_cv.reset(token)


# ─── current_speaker_name（聊天室发言者）─────────────────


def get_current_speaker_name() -> Optional[str]:
    return _current_speaker_name_cv.get()


def set_current_speaker_name(name: Optional[str]) -> Token:
    return _current_speaker_name_cv.set(name)


def reset_current_speaker_name(token: Token) -> None:
    _current_speaker_name_cv.reset(token)


# ─── current_create_counter（单 task 内 create_agent 上限）────


def get_current_create_counter() -> Optional[List[int]]:
    return _current_create_counter_cv.get()


def set_current_create_counter(counter: Optional[List[int]]) -> Token:
    return _current_create_counter_cv.set(counter)


def reset_current_create_counter(token: Token) -> None:
    _current_create_counter_cv.reset(token)


# ─── current_parent_message_id（chatroom dispatch reply 链路）─────


def get_current_parent_message_id() -> Optional[str]:
    return _current_parent_message_id_cv.get()


def set_current_parent_message_id(message_id: Optional[str]) -> Token:
    return _current_parent_message_id_cv.set(message_id)


def reset_current_parent_message_id(token: Token) -> None:
    _current_parent_message_id_cv.reset(token)
