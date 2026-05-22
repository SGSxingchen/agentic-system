"""TaskRegistry tests for the Agent Run model."""

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
    ts = registry.create(requirement="build login", agent_name="assistant")

    assert isinstance(ts, TaskState)
    assert ts.status is TaskStatus.PENDING
    assert ts.type is TaskType.AGENT_RUN
    assert ts.agent_name == "assistant"
    assert ts.requirement == "build login"
    assert ts.id in registry
    assert len(registry) == 1


def test_list_returns_tasks_in_recency_order() -> None:
    registry = TaskRegistry()
    a = registry.create(requirement="a")
    b = registry.create(requirement="b")

    ordered = registry.list()
    ids = [t.id for t in ordered]

    assert set(ids) == {a.id, b.id}
    assert ids[0] == b.id


def test_set_progress_merges_fields() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r")

    registry.set_progress(ts.id, tool_count=3, total_tokens=1500, activity="planning")
    registry.set_progress(ts.id, tool_count=2, last_tool="bash", current_step="code")

    progress: AgentProgress = registry.get(ts.id).progress
    assert progress.tool_count == 5
    assert progress.total_tokens == 1500
    assert progress.activity == "planning"
    assert progress.last_tool == "bash"
    assert progress.current_step == "code"


def test_mark_done_sets_status_and_ended_at() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r")

    registry.update(ts.id, status=TaskStatus.RUNNING)
    registry.mark_done(ts.id, TaskStatus.COMPLETED, output={"plan": [1, 2, 3]})

    state = registry.get(ts.id)
    assert state.status is TaskStatus.COMPLETED
    assert state.output == {"plan": [1, 2, 3]}
    assert state.ended_at is not None


def test_to_dict_serializes_enums() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r", agent_name="assistant")
    registry.set_progress(ts.id, tool_count=1, activity="thinking")

    payload = registry.get(ts.id).to_dict()

    assert payload["status"] == "pending"
    assert payload["type"] == "agent_run"
    assert payload["progress"]["tool_count"] == 1
    assert payload["progress"]["activity"] == "thinking"
    assert "pipeline" not in payload
    assert payload["agent_name"] == "assistant"


async def test_kill_cancels_attached_asyncio_task() -> None:
    registry = TaskRegistry()
    ts = registry.create(requirement="r")

    cancelled = asyncio.Event()

    async def long_running() -> None:
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    asyncio_task = asyncio.create_task(long_running())
    registry.attach(ts.id, asyncio_task)

    await asyncio.sleep(0.01)

    assert registry.kill(ts.id) is True

    with pytest.raises(asyncio.CancelledError):
        await asyncio_task

    assert cancelled.is_set()


def test_kill_unknown_task_returns_false() -> None:
    registry = TaskRegistry()
    assert registry.kill("does-not-exist") is False


async def test_kill_cascades_to_child_tasks() -> None:
    registry = TaskRegistry()

    parent = registry.create(requirement="p")
    child = registry.create(requirement="c", parent_id=parent.id)

    cancellations = {parent.id: asyncio.Event(), child.id: asyncio.Event()}

    async def _runner(tid: str) -> None:
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            cancellations[tid].set()
            raise

    parent_task = asyncio.create_task(_runner(parent.id))
    child_task = asyncio.create_task(_runner(child.id))
    registry.attach(parent.id, parent_task)
    registry.attach(child.id, child_task)

    await asyncio.sleep(0.01)

    assert registry.kill(parent.id) is True

    for task in (parent_task, child_task):
        with pytest.raises(asyncio.CancelledError):
            await task

    assert cancellations[parent.id].is_set()
    assert cancellations[child.id].is_set()


def test_list_children_returns_only_direct_children() -> None:
    registry = TaskRegistry()
    parent = registry.create(requirement="p")
    child_one = registry.create(requirement="c1", parent_id=parent.id)
    child_two = registry.create(requirement="c2", parent_id=parent.id)
    other = registry.create(requirement="other")

    children = registry.list_children(parent.id)
    ids = {child.id for child in children}

    assert ids == {child_one.id, child_two.id}
    assert other.id not in ids


def test_create_agent_run_state_has_instance_fields() -> None:
    registry = TaskRegistry()
    state = registry.create(
        task_type=TaskType.AGENT_RUN,
        requirement="ship autonomous scheduler",
        agent_name="assistant",
        session_id="session-a",
        workspace_id="workspace-a",
        mode="autonomous",
        strategy="agent_decides",
    )

    payload = state.to_dict()

    assert payload["type"] == "agent_run"
    assert payload["run_id"] == state.id
    assert payload["goal"] == "ship autonomous scheduler"
    assert payload["agent_name"] == "assistant"
    assert payload["session_id"] == "session-a"
    assert payload["workspace_id"] == "workspace-a"
    assert payload["strategy"] == "agent_decides"


def test_create_agent_run_state_has_continuous_goal_fields() -> None:
    registry = TaskRegistry()
    state = registry.create(
        task_type=TaskType.AGENT_RUN,
        requirement="持续优化项目直到可演示",
        agent_name="assistant",
        mode="continuous",
        strategy="memory_guided_agent_loop",
        max_iterations=80,
        completion_criteria="前端构建通过，目标工作台可用",
        auto_memory=True,
    )

    payload = state.to_dict()

    assert payload["mode"] == "continuous"
    assert payload["strategy"] == "memory_guided_agent_loop"
    assert payload["max_iterations"] == 80
    assert payload["iteration"] == 0
    assert payload["completion_criteria"] == "前端构建通过，目标工作台可用"
    assert payload["auto_memory"] is True


def test_pause_and_resume_agent_run() -> None:
    registry = TaskRegistry()
    state = registry.create(
        task_type=TaskType.AGENT_RUN,
        requirement="持续推进目标",
        agent_name="assistant",
    )
    registry.update(state.id, status=TaskStatus.RUNNING)

    assert registry.pause(state.id) is True
    assert registry.get(state.id).status is TaskStatus.PAUSED

    assert registry.resume(state.id) is True
    assert registry.get(state.id).status is TaskStatus.RUNNING


def test_pause_terminal_agent_run_returns_false() -> None:
    registry = TaskRegistry()
    state = registry.create(
        task_type=TaskType.AGENT_RUN,
        requirement="已经完成",
        agent_name="assistant",
    )
    registry.mark_done(state.id, TaskStatus.COMPLETED, output={"ok": True})

    assert registry.pause(state.id) is False
    assert registry.get(state.id).status is TaskStatus.COMPLETED
