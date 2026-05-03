"""Workspace default directory behavior tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import core.workspace as workspace_module
from capabilities.tools._safety import (
    get_workspace_root,
    resolve_workspace_cwd,
    resolve_workspace_path,
)
from capabilities.tools.bash import BashCapability
from core.artifacts import ArtifactStore
from core.config import FileToolConfig, load_config, load_system_config
from core.task.transcript import TranscriptWriter


def _patch_project_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(workspace_module, "project_root", lambda: root)


def test_default_workspace_root_is_project_workspace_and_created(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTIC_WORKSPACE_ROOT", raising=False)
    _patch_project_root(monkeypatch, tmp_path)

    root = get_workspace_root()

    assert root == (tmp_path / "workspace").resolve()
    assert root.is_dir()


def test_config_defaults_to_workspace_when_no_user_config(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTIC_WORKSPACE_ROOT", raising=False)
    config = load_config(config_path=tmp_path / "missing.yaml", config_dir=tmp_path / "config")
    typed = load_system_config(tmp_path / "missing.yaml")

    assert config["tools"]["file"]["workspace_root"] == "./workspace"
    assert FileToolConfig().workspace_root == "./workspace"
    assert typed.tools.file.workspace_root == "./workspace"


def test_workspace_path_resolution_is_under_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTIC_WORKSPACE_ROOT", raising=False)
    _patch_project_root(monkeypatch, tmp_path)

    resolved = resolve_workspace_path("outputs/result.txt")

    assert resolved == (tmp_path / "workspace" / "outputs" / "result.txt").resolve()
    assert (tmp_path / "workspace").is_dir()


@pytest.mark.asyncio
async def test_bash_default_cwd_is_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_SHELL_TOOL", "true")
    monkeypatch.delenv("AGENTIC_WORKSPACE_ROOT", raising=False)
    _patch_project_root(monkeypatch, tmp_path)

    result = await BashCapability().execute(command="pwd")

    assert result["returncode"] == 0
    assert result["cwd"] == str((tmp_path / "workspace").resolve())
    assert result["stdout"].strip() == result["cwd"]


@pytest.mark.asyncio
async def test_bash_explicit_cwd_inside_workspace_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_SHELL_TOOL", "true")
    monkeypatch.delenv("AGENTIC_WORKSPACE_ROOT", raising=False)
    _patch_project_root(monkeypatch, tmp_path)
    explicit = tmp_path / "workspace" / "nested"
    explicit.mkdir(parents=True)

    resolved = resolve_workspace_cwd("nested")
    result = await BashCapability().execute(command="pwd", cwd="nested")

    assert resolved == explicit.resolve()
    assert result["returncode"] == 0
    assert result["cwd"] == str(explicit.resolve())
    assert result["stdout"].strip() == result["cwd"]


@pytest.mark.asyncio
async def test_explicit_workspace_root_env_is_not_overridden(tmp_path, monkeypatch):
    custom = tmp_path / "custom-agent-workspace"
    monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(custom))
    monkeypatch.setenv("ENABLE_SHELL_TOOL", "true")
    _patch_project_root(monkeypatch, tmp_path / "project")

    result = await BashCapability().execute(command="pwd")

    assert get_workspace_root() == custom.resolve()
    assert result["cwd"] == str(custom.resolve())
    assert result["stdout"].strip() == str(custom.resolve())


def test_artifact_default_store_is_workspace_artifacts(tmp_path, monkeypatch):
    monkeypatch.delenv("ARTIFACT_STORE_DIR", raising=False)
    _patch_project_root(monkeypatch, tmp_path)

    artifact = ArtifactStore().create_artifact(
        kind="text",
        title="hello",
        content="workspace artifact",
        filename="hello.txt",
    )

    store = ArtifactStore()
    assert store.root == (tmp_path / "workspace" / "artifacts").resolve()
    assert store.get_file_path(artifact).is_file()
    assert str(store.get_file_path(artifact)).startswith(str(store.root))


def test_transcript_default_store_is_workspace_tasks(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTIC_TASK_DATA_DIR", raising=False)
    _patch_project_root(monkeypatch, tmp_path)

    writer = TranscriptWriter("workspace-task")
    writer.write("start")

    assert writer.path == (tmp_path / "workspace" / "tasks" / "workspace-task.jsonl").resolve()
    assert writer.path.is_file()


def test_dispatch_worktrees_follow_explicit_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path / "custom-workspace"))
    _patch_project_root(monkeypatch, tmp_path / "project")

    from capabilities.tools import dispatch_agent

    assert (dispatch_agent.get_workspace_root() / dispatch_agent._WORKTREES_DIRNAME) == (
        tmp_path / "custom-workspace" / "worktrees"
    ).resolve()
