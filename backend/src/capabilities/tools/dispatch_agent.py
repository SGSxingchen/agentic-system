"""dispatch_agent — v2 Phase C 支柱 4：派发非阻塞子 Agent 任务

调用此工具的 Agent 立即拿到 ``task_id`` 并继续工作；子 Agent 完成时,
其结果会以 ``<task-notification>`` user 消息追加到当前 Agent 的对话历史。

设计要点:
- 解析 subagent_type → CapabilityRegistry 中已注册的 AgentCapability
- 通过 contextvars 取父 task_id / 父 notification_box（避免改 Agent / Pipeline 接口）
- 可选 ``worktree=true``: 创建临时 git worktree 并设置 workspace_root_cv 隔离子 Agent 的文件操作
- ``max_depth=1``: 子 Agent 内部再调 dispatch_agent 直接返错（防递归）
- 子任务异常 / cancel / 完成都会回写 TaskRegistry 状态 + 父 notification_box + transcript
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.capability.base import CapabilityBase, CapabilitySchema
from core.task import (
    TaskStatus,
    TaskType,
    TranscriptWriter,
    get_dispatch_depth,
    get_notification_box,
    get_parent_task_id,
    reset_dispatch_depth,
    reset_workspace_root_override,
    set_dispatch_depth,
    set_workspace_root_override,
)

from ._safety import get_workspace_root

logger = logging.getLogger(__name__)

_WORKTREES_DIRNAME = "data/worktrees"
_MAX_DEPTH = 1


class DispatchAgentCapability(CapabilityBase):
    """非阻塞地派发已注册的子 Agent；返回 task_id, 子任务完成时回注通知。"""

    @property
    def name(self) -> str:
        return "dispatch_agent"

    @property
    def description(self) -> str:
        return (
            "派发一个已注册的子 Agent 异步执行子任务，立即返回 task_id；"
            "子任务完成时会以 <task-notification> 形式追加到本对话。"
            "适合在 planner / coder 内并行委派工作，无需阻塞等待。"
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "subagent_type": {
                        "type": "string",
                        "description": "已注册的子 Agent 名（如 coder / reviewer）",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "给子 Agent 的输入文本",
                    },
                    "worktree": {
                        "type": "boolean",
                        "description": "是否在独立 git worktree 隔离运行（默认 false）",
                        "default": False,
                    },
                    "description": {
                        "type": "string",
                        "description": "可选：任务描述，仅用于前端展示",
                    },
                },
                "required": ["subagent_type", "prompt"],
            },
            returns="包含 task_id / status / summary 的字典；status='dispatched' 表示已派发",
            is_read_only=False,
            is_concurrency_safe=True,
            max_result_size=2000,
        )

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        depth = get_dispatch_depth()
        if depth >= _MAX_DEPTH:
            return {
                "decision": "deny",
                "reason": (
                    f"nested dispatch_agent is not allowed "
                    f"(current depth={depth}, max={_MAX_DEPTH})"
                ),
            }
        return {"decision": "allow"}

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        subagent_type = str(kwargs.get("subagent_type") or "").strip()
        prompt = str(kwargs.get("prompt") or "").strip()
        worktree_requested = bool(kwargs.get("worktree", False))
        description = str(kwargs.get("description") or "").strip()

        if not subagent_type:
            return {"error": "subagent_type is required"}
        if not prompt:
            return {"error": "prompt is required"}

        # 嵌套深度二次校验（防止绕过 check_permissions 直接 execute）
        if get_dispatch_depth() >= _MAX_DEPTH:
            return {
                "error": (
                    f"nested dispatch_agent is not allowed "
                    f"(max_depth={_MAX_DEPTH})"
                ),
                "permission_denied": True,
            }

        # 解析子 Agent
        cap_registry = _get_capability_registry()
        if cap_registry is None:
            return {"error": "capability registry is not initialized"}
        subagent_cap = cap_registry.get(subagent_type)
        if subagent_cap is None:
            return {"error": f"unknown subagent_type: '{subagent_type}'"}

        # TaskRegistry
        task_registry = _get_task_registry()
        if task_registry is None:
            return {"error": "task registry is not available"}

        parent_task_id = get_parent_task_id()
        notification_box = get_notification_box()

        # 创建子 task 状态
        sub_state = task_registry.create(
            task_type=TaskType.SUB_AGENT,
            requirement=prompt,
            pipeline_name=f"sub:{subagent_type}",
            parent_id=parent_task_id,
        )
        writer = TranscriptWriter(sub_state.id)
        writer.write(
            "created",
            {
                "subagent_type": subagent_type,
                "parent_id": parent_task_id,
                "description": description,
                "worktree": worktree_requested,
            },
        )

        # 可选 worktree
        worktree_path: Optional[Path] = None
        if worktree_requested:
            try:
                worktree_path = await _create_worktree(sub_state.id)
                writer.write("worktree_created", {"path": str(worktree_path)})
            except Exception as exc:
                task_registry.mark_done(
                    sub_state.id,
                    TaskStatus.FAILED,
                    error=f"worktree creation failed: {exc}",
                )
                writer.write("error", {"error": f"worktree creation failed: {exc}"})
                return {
                    "error": f"failed to create worktree: {exc}",
                    "task_id": sub_state.id,
                }

        # 派发后台执行
        coro = _run_subagent(
            sub_state.id,
            subagent_type,
            prompt,
            subagent_cap,
            worktree_path,
            notification_box,
            task_registry,
            writer,
        )
        async_task = asyncio.create_task(coro)
        task_registry.attach(sub_state.id, async_task)
        task_registry.update(sub_state.id, status=TaskStatus.RUNNING)

        return {
            "task_id": sub_state.id,
            "subagent_type": subagent_type,
            "status": "dispatched",
            "summary": (
                f"Spawned {subagent_type} as task {sub_state.id[:8]}; "
                "result will arrive as a <task-notification>"
            ),
            "worktree": str(worktree_path) if worktree_path else None,
        }


# ─── 内部：运行子 Agent ──────────────────────────────────


async def _run_subagent(
    task_id: str,
    subagent_type: str,
    prompt: str,
    subagent_cap: CapabilityBase,
    worktree_path: Optional[Path],
    parent_box: Optional[list],
    task_registry: Any,
    writer: TranscriptWriter,
) -> None:
    """子 Agent 协程：跑 subagent_cap.execute → 终态写 TaskRegistry + 父 box + transcript。"""
    depth_token = set_dispatch_depth(_MAX_DEPTH)  # 子 Agent 不能再嵌套派生
    wsr_token = (
        set_workspace_root_override(worktree_path) if worktree_path else None
    )
    started = asyncio.get_event_loop().time()
    try:
        writer.write("started", {})
        result = await subagent_cap.execute(message=prompt)

        task_registry.mark_done(task_id, TaskStatus.COMPLETED, output=result)
        writer.write(
            "done",
            {"status": "completed", "duration_ms": _elapsed_ms(started)},
        )

        if parent_box is not None:
            parent_box.append(
                {
                    "task_id": task_id,
                    "subagent_type": subagent_type,
                    "status": "completed",
                    "result": result,
                    "usage": _extract_usage(result),
                    "duration_ms": _elapsed_ms(started),
                }
            )

    except asyncio.CancelledError:
        task_registry.mark_done(task_id, TaskStatus.KILLED, error="cancelled by parent")
        writer.write("killed", {})
        if parent_box is not None:
            parent_box.append(
                {
                    "task_id": task_id,
                    "subagent_type": subagent_type,
                    "status": "killed",
                    "duration_ms": _elapsed_ms(started),
                }
            )
        raise

    except Exception as exc:
        logger.exception("dispatch_agent: subagent '%s' failed", subagent_type)
        task_registry.mark_done(task_id, TaskStatus.FAILED, error=str(exc))
        writer.write("error", {"error": str(exc)})
        if parent_box is not None:
            parent_box.append(
                {
                    "task_id": task_id,
                    "subagent_type": subagent_type,
                    "status": "failed",
                    "error": str(exc),
                    "duration_ms": _elapsed_ms(started),
                }
            )

    finally:
        reset_dispatch_depth(depth_token)
        if wsr_token is not None:
            reset_workspace_root_override(wsr_token)


# ─── 内部辅助 ───────────────────────────────────────────


def _elapsed_ms(started_at: float) -> int:
    return int((asyncio.get_event_loop().time() - started_at) * 1000)


def _extract_usage(result: Any) -> Dict[str, int]:
    if isinstance(result, dict):
        usage = result.get("usage")
        if isinstance(usage, dict):
            return usage
    return {}


def _get_capability_registry():
    try:
        from api.dependencies import get_capability_registry as _g
        return _g()
    except Exception:
        return None


def _get_task_registry():
    try:
        from api.routes.tasks import get_task_registry as _g
        return _g()
    except Exception:
        return None


# ─── Worktree 创建 ──────────────────────────────────────


async def _create_worktree(task_id: str) -> Path:
    """在工作区根创建一个 git worktree (detached HEAD)。

    成功返回 worktree 绝对路径；任何错误抛 RuntimeError。
    """
    project_root = get_workspace_root()
    worktrees_root = project_root / _WORKTREES_DIRNAME
    worktrees_root.mkdir(parents=True, exist_ok=True)
    target = worktrees_root / task_id

    proc = await asyncio.create_subprocess_exec(
        "git",
        "worktree",
        "add",
        "--detach",
        str(target),
        "HEAD",
        cwd=str(project_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed (code={proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )

    return target.resolve()
