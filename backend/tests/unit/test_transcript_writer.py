"""TranscriptWriter 单元测试（v2 Phase B）"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.task.transcript import TranscriptWriter, read_transcript


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """每个测试都使用独立 workspace/tasks 目录，避免 cross-test 污染。"""
    monkeypatch.setenv("AGENTIC_TASK_DATA_DIR", str(tmp_path / "tasks"))


def test_writes_jsonl_lines() -> None:
    w = TranscriptWriter("task-001")
    w.write("start", {"requirement": "x"})
    w.write("step_started", {"step": "plan"})
    w.write("step_completed", {"step": "plan", "elapsed_ms": 12.5})

    events = read_transcript("task-001")
    assert len(events) == 3
    assert events[0]["type"] == "start"
    assert events[0]["payload"]["requirement"] == "x"
    assert events[2]["payload"]["elapsed_ms"] == 12.5


def test_creates_directory_if_missing(tmp_path, monkeypatch) -> None:
    target = tmp_path / "fresh" / "tasks"
    monkeypatch.setenv("AGENTIC_TASK_DATA_DIR", str(target))

    assert not target.exists()
    w = TranscriptWriter("task-002")
    w.write("start")

    assert target.exists()
    expected_file = target / "task-002.jsonl"
    assert expected_file.exists()


def test_read_returns_empty_for_unknown_task() -> None:
    assert read_transcript("never-existed") == []


def test_read_skips_malformed_lines(tmp_path, monkeypatch) -> None:
    target = tmp_path / "tasks"
    target.mkdir(parents=True)
    monkeypatch.setenv("AGENTIC_TASK_DATA_DIR", str(target))

    file = target / "task-003.jsonl"
    file.write_text(
        json.dumps({"ts": "t1", "type": "start", "payload": {}}) + "\n"
        + "not-json\n"
        + json.dumps({"ts": "t2", "type": "done", "payload": {}}) + "\n",
        encoding="utf-8",
    )

    events = read_transcript("task-003")
    assert len(events) == 2
    assert [e["type"] for e in events] == ["start", "done"]
