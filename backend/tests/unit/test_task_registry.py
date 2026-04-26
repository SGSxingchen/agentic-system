"""TaskRegistry 单元测试（v2 Phase B）"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.task import (
    AgentProgress,
    TaskRegistry,
    TaskState,
    TaskStatus,
    TaskType,
)


def test_create_returns_pending_task() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="build login", pipeline_name="full_pipeline")

    assert isinstance(ts, TaskState)
    assert ts.status is TaskStatus.PENDING
    assert ts.type is TaskType.PIPELINE
    assert ts.pipeline_name == "full_pipeline"
    assert ts.requirement == "build login"
    assert ts.id in registry
    assert len(registry) == 1


def test_list_returns_tasks_in_recency_order() -> None:
    registry = TaskRegistry()
    a = registry.create(requirement="a", pipeline_name="x")
    b = registry.create(requirement="b", pipeline_name="x")

    ordered = registry.list()
    ids = [t.id for t in ordered]

    assert set(ids) == {a.id, b.id}
    # b 创建在后，按倒序排在前
    assert ids[0] == b.id


def test_set_progress_merges_fields() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r", pipeline_name="p")

    registry.set_progress(ts.id, tool_count=3, total_tokens=1500, activity="planning")
    registry.set_progress(ts.id, tool_count=2, last_tool="bash", current_step="code")

    progress: AgentProgress = registry.get(ts.id).progress
    assert progress.tool_count == 5  # 累加
    assert progress.total_tokens == 1500
    assert progress.activity == "planning"  # 第二次未传入，保留
    assert progress.last_tool == "bash"
    assert progress.current_step == "code"


def test_mark_done_sets_status_and_ended_at() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r", pipeline_name="p")

    registry.update(ts.id, status=TaskStatus.RUNNING)
    registry.mark_done(ts.id, TaskStatus.COMPLETED, output={"plan": [1, 2, 3]})

    state = registry.get(ts.id)
    assert state.status is TaskStatus.COMPLETED
    assert state.output == {"plan": [1, 2, 3]}
    assert state.ended_at is not None


def test_to_dict_serializes_enums() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r", pipeline_name="p")
    registry.set_progress(ts.id, tool_count=1, activity="thinking")

    payload = registry.get(ts.id).to_dict()

    assert payload["status"] == "pending"
    assert payload["type"] == "pipeline"
    assert payload["progress"]["tool_count"] == 1
    assert payload["progress"]["activity"] == "thinking"
    assert payload["pipeline"] == "p"


async def test_kill_cancels_attached_asyncio_task() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r", pipeline_name="p")

    cancelled = asyncio.Event()

    async def long_running() -> None:
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    asyncio_task = asyncio.create_task(long_running())
    registry.attach(ts.id, asyncio_task)

    # 让任务有机会启动
    await asyncio.sleep(0.01)

    assert registry.kill(ts.id) is True

    # 等待 cancellation 真正生效
    with pytest.raises(asyncio.CancelledError):
        await asyncio_task

    assert cancelled.is_set()


def test_kill_unknown_task_returns_false() -> None:
    registry = TaskRegistry()
    assert registry.kill("does-not-exist") is False
