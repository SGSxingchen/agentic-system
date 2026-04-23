"""Pipeline 与 WorkflowOrchestrator 的执行保障测试。"""
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.agent.registry import AgentRegistry
from core.capability import CapabilityRegistry
from core.capability.base import CapabilityBase, CapabilitySchema
from core.pipeline import Pipeline, PipelineConfig, PipelineStatus, PipelineStep
from core.workflow import Task, WorkflowOrchestrator, WorkflowStatus


class EchoCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo input"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self.name, description=self.description)

    async def execute(self, **kwargs: Any) -> Any:
        return kwargs


class SlowCapability(CapabilityBase):
    @property
    def name(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "sleep before returning"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(name=self.name, description=self.description)

    async def execute(self, **kwargs: Any) -> Any:
        await asyncio.sleep(0.05)
        return {"done": True}


class StubAgent:
    def __init__(self, name: str, handler):
        self.name = name
        self._handler = handler

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self._handler(input_data)


@pytest.fixture
def capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register_native(EchoCapability())
    registry.register_native(SlowCapability())
    return registry


@pytest.mark.asyncio
async def test_pipeline_resolves_nested_variables(capability_registry):
    bus = MagicMock()
    bus.publish = AsyncMock()
    pipeline = Pipeline(capability_registry, bus=bus)

    config = PipelineConfig(
        name="nested-inputs",
        steps=[
            PipelineStep(
                name="echo-step",
                capability="echo",
                input_data={
                    "items": ["hello ${name}", {"payload": "${payload}"}],
                    "pair": ("${name}", "${payload}"),
                },
                output_key="result",
            )
        ],
    )

    payload = {"approved": True}
    result = await pipeline.execute(
        config,
        initial_context={"name": "codex", "payload": payload},
    )

    assert result.status == PipelineStatus.COMPLETED
    assert result.context["result"]["items"] == ["hello codex", {"payload": payload}]
    assert result.context["result"]["pair"] == ("codex", payload)


@pytest.mark.asyncio
async def test_pipeline_step_timeout_marks_failure(capability_registry):
    bus = MagicMock()
    bus.publish = AsyncMock()
    pipeline = Pipeline(capability_registry, bus=bus)

    config = PipelineConfig(
        name="timeout",
        steps=[
            PipelineStep(
                name="slow-step",
                capability="slow",
                timeout=0.01,
            )
        ],
    )

    result = await pipeline.execute(config)

    assert result.status == PipelineStatus.FAILED
    assert result.error == "Step 'slow-step' failed: Step 'slow-step' timed out after 0.01s"
    assert result.step_results[0].status == PipelineStatus.FAILED
    assert "timed out" in result.step_results[0].error


@pytest.mark.asyncio
async def test_workflow_resolves_nested_variables():
    registry = AgentRegistry()

    async def echo_handler(input_data: Dict[str, Any]) -> Dict[str, Any]:
        return input_data

    registry.register(StubAgent("echo", echo_handler))

    orchestrator = WorkflowOrchestrator(registry, MagicMock())
    tasks = [
        Task(
            name="echo-task",
            agent="echo",
            input_data={
                "items": ["${name}", {"payload": "${payload}"}],
                "message": "hello ${name}",
            },
            output_key="echoed",
        )
    ]

    payload = {"kind": "review"}
    result = await orchestrator.execute_sequential(
        tasks,
        initial_context={"name": "planner", "payload": payload},
    )

    assert result.status == WorkflowStatus.COMPLETED
    assert result.context["echoed"]["items"] == ["planner", {"payload": payload}]
    assert result.context["echoed"]["message"] == "hello planner"


@pytest.mark.asyncio
async def test_workflow_task_timeout_marks_failure():
    registry = AgentRegistry()

    async def slow_handler(_: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"done": True}

    registry.register(StubAgent("slow", slow_handler))

    orchestrator = WorkflowOrchestrator(registry, MagicMock())
    tasks = [Task(name="slow-task", agent="slow", timeout=0.01)]

    result = await orchestrator.execute_sequential(tasks)

    assert result.status == WorkflowStatus.FAILED
    assert result.error == "Task 'slow-task' failed: Task 'slow-task' timed out after 0.01s"
    assert result.task_results[0].status == WorkflowStatus.FAILED
    assert "timed out" in result.task_results[0].error
