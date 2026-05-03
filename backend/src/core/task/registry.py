"""TaskRegistry — 异步任务注册中心（v2 Phase B 支柱 2）

职责:
- 创建 TaskState 实例（返回一个新的 task_id）
- 关联 asyncio.Task 句柄，用于 kill (cooperative cancel)
- 增量更新进度 / 状态 / 中间结果
- 列表查询（前端轮询使用）

不负责:
- transcript 落盘（由 TranscriptWriter 处理）
- Pipeline 执行细节（由 routes/tasks.py + Pipeline 处理）
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .types import AgentProgress, TaskState, TaskStatus, TaskType

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat()


class TaskRegistry:
    """进程级单例风格的 Task 注册中心。

    线程安全注记：所有方法应在同一 asyncio loop 内调用。
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskState] = {}
        self._asyncio_tasks: Dict[str, asyncio.Task] = {}

    # ─── 创建 / 关联 ───────────────────────────────────────

    def create(
        self,
        *,
        task_type: TaskType = TaskType.PIPELINE,
        requirement: str,
        pipeline_name: str = "",
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        mode: str = "autonomous",
        strategy: str = "agent_decides",
        parent_id: Optional[str] = None,
        output_file: Optional[str] = None,
    ) -> TaskState:
        """新建一条 TaskState（PENDING）。

        ``pipeline_name`` 保持默认空值，使新的 Agent Run 不必伪装成管线。
        """
        task_id = str(uuid.uuid4())
        state = TaskState(
            id=task_id,
            type=task_type,
            requirement=requirement,
            pipeline_name=pipeline_name,
            agent_name=agent_name,
            session_id=session_id,
            workspace_id=workspace_id,
            mode=mode,
            strategy=strategy,
            parent_id=parent_id,
            output_file=output_file,
        )
        self._tasks[task_id] = state
        return state

    def attach(self, task_id: str, asyncio_task: asyncio.Task) -> None:
        """把执行中的 asyncio.Task 关联到 task_id（供 kill 使用）。"""
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not registered before attach")
        self._asyncio_tasks[task_id] = asyncio_task

    # ─── 查询 ─────────────────────────────────────────────

    def get(self, task_id: str) -> Optional[TaskState]:
        return self._tasks.get(task_id)

    def list(self) -> List[TaskState]:
        """返回所有 task；按插入顺序倒序（最新在前）。

        用 dict 插入序而非 created_at 字符串：Windows 上 datetime 分辨率约
        16ms，连续 create() 时间戳会相同，字符串排序退化为稳定排序导致顺序错乱。
        """
        return list(reversed(self._tasks.values()))

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._tasks

    def __len__(self) -> int:
        return len(self._tasks)

    # ─── 更新 ─────────────────────────────────────────────

    def update(self, task_id: str, **fields: Any) -> Optional[TaskState]:
        """原子更新若干字段并 bump updated_at。

        允许的字段集合等同 TaskState 的属性；未知字段会被忽略并打 warning。
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None

        for key, value in fields.items():
            if key == "progress" and isinstance(value, dict):
                # progress 走专门的合并通道
                self._merge_progress(task.progress, value)
                continue
            if hasattr(task, key):
                setattr(task, key, value)
            else:
                logger.warning("TaskRegistry.update: unknown field '%s'", key)

        task.touch()
        return task

    def set_progress(self, task_id: str, **delta: Any) -> Optional[TaskState]:
        """合并 progress 字段（增量；tool_count / total_tokens 累加；其他覆盖）。"""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        self._merge_progress(task.progress, delta)
        task.touch()
        return task

    def mark_done(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        output: Any = None,
        error: Optional[str] = None,
    ) -> Optional[TaskState]:
        """终态收尾：写 ended_at、可选 output/error、并解除 asyncio_task 关联。"""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = status
        if output is not None:
            task.output = output
        if error is not None:
            task.error = error
        task.ended_at = _now_iso()
        task.touch()
        self._asyncio_tasks.pop(task_id, None)
        return task

    # ─── 取消 ─────────────────────────────────────────────

    def kill(self, task_id: str) -> bool:
        """对关联的 asyncio.Task 发出 cancel；级联取消所有未终态的子任务。

        Returns:
            是否成功定位 task_id（无论是否级联了子任务）。
        """
        if task_id not in self._tasks:
            return False

        # 先递归 kill 子任务（避免遗留孤儿）
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.KILLED}
        for child in list(self._tasks.values()):
            if child.parent_id == task_id and child.status not in terminal:
                self.kill(child.id)

        asyncio_task = self._asyncio_tasks.get(task_id)
        if asyncio_task is not None and not asyncio_task.done():
            asyncio_task.cancel()
        return True

    def list_children(self, parent_id: str) -> List[TaskState]:
        """列出某个父任务的所有子任务（按插入顺序倒序）。"""
        return [
            t for t in reversed(self._tasks.values()) if t.parent_id == parent_id
        ]

    # ─── 内部：progress 合并 ──────────────────────────────

    @staticmethod
    def _merge_progress(progress: AgentProgress, delta: Dict[str, Any]) -> None:
        """tool_count / total_tokens 累加；其他字段覆盖（仅当传入非 None）。"""
        if "tool_count" in delta and delta["tool_count"] is not None:
            progress.tool_count += int(delta["tool_count"])
        if "total_tokens" in delta and delta["total_tokens"] is not None:
            progress.total_tokens += int(delta["total_tokens"])
        if "activity" in delta and delta["activity"] is not None:
            progress.activity = str(delta["activity"])
        if "last_tool" in delta and delta["last_tool"] is not None:
            progress.last_tool = str(delta["last_tool"])
        if "current_step" in delta and delta["current_step"] is not None:
            progress.current_step = str(delta["current_step"])
