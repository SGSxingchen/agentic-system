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
