"""Managed workspace API tests."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import core.workspace as workspace_module
from api.routes.workspaces import router as workspaces_router
from api.routes.tasks import _run_workspace
from core.workspace import WorkspaceStore, session_workspace_id


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_module, "project_root", lambda: tmp_path)

    app = FastAPI()
    app.include_router(workspaces_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


async def test_import_zip_registers_project_workspace(client, tmp_path):
    archive = _zip_bytes(
        {
            "README.md": "# Demo",
            "src/app.py": "print('hello')\n",
            "docs/guide.txt": "guide",
        }
    )

    response = await client.post(
        "/api/workspaces/import",
        data={"name": "Demo Project", "description": "Imported for tests"},
        files={"file": ("demo-project.zip", archive, "application/zip")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    workspace = body["data"]
    assert workspace["id"] == "demo-project"
    assert workspace["kind"] == "project"
    assert workspace["source"] == "zip_upload"
    assert workspace["metadata"]["description"] == "Imported for tests"

    root_path = Path(workspace["root_path"])
    assert root_path == (tmp_path / "workspace" / "projects" / "demo-project").resolve()
    assert (root_path / "src" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert (root_path / ".agentic-workspace.json").is_file()


async def test_import_zip_slip_is_rejected(client, tmp_path):
    archive = _zip_bytes({"../evil.txt": "owned"})

    response = await client.post(
        "/api/workspaces/import",
        data={"name": "Unsafe"},
        files={"file": ("unsafe.zip", archive, "application/zip")},
    )

    assert response.status_code == 400
    assert "unsafe path" in response.json()["detail"]
    assert not (tmp_path / "evil.txt").exists()

    list_response = await client.get("/api/workspaces")
    assert list_response.status_code == 200
    assert list_response.json()["data"] == []


async def test_list_and_get_workspace_detail_include_files(client):
    archive = _zip_bytes({"src/main.py": "print(1)\n", "notes/todo.txt": "todo"})
    import_response = await client.post(
        "/api/workspaces/import",
        data={"name": "Readable Workspace"},
        files={"file": ("readable.zip", archive, "application/zip")},
    )
    workspace_id = import_response.json()["data"]["id"]

    list_response = await client.get("/api/workspaces")
    assert list_response.status_code == 200
    workspaces = list_response.json()["data"]
    assert [item["id"] for item in workspaces] == [workspace_id]

    detail_response = await client.get(f"/api/workspaces/{workspace_id}?depth=3&limit=20")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    paths = {item["path"] for item in detail["files"]}
    assert detail["id"] == workspace_id
    assert detail["files_truncated"] is False
    assert {"src", "src/main.py", "notes/todo.txt"}.issubset(paths)


async def test_workspace_text_file_can_be_read_and_edited(client):
    archive = _zip_bytes({"drafts/chapter-01.md": "第一版\n"})
    import_response = await client.post(
        "/api/workspaces/import",
        data={"name": "Novel Workspace"},
        files={"file": ("novel.zip", archive, "application/zip")},
    )
    workspace_id = import_response.json()["data"]["id"]

    read_response = await client.get(
        f"/api/workspaces/{workspace_id}/files/content",
        params={"path": "drafts/chapter-01.md"},
    )

    assert read_response.status_code == 200
    payload = read_response.json()["data"]
    assert payload["content"] == "第一版\n"
    assert payload["editable"] is True

    write_response = await client.put(
        f"/api/workspaces/{workspace_id}/files/content",
        json={"path": "drafts/chapter-01.md", "content": "第二版\n"},
    )

    assert write_response.status_code == 200
    assert write_response.json()["data"]["content"] == "第二版\n"

    detail_response = await client.get(f"/api/workspaces/{workspace_id}", params={"include_files": False})
    detail = detail_response.json()["data"]
    assert "last_file_edit_at" in detail["metadata"]


async def test_workspace_file_api_rejects_unsafe_relative_paths(client):
    archive = _zip_bytes({"safe.txt": "safe"})
    import_response = await client.post(
        "/api/workspaces/import",
        data={"name": "Safe Workspace"},
        files={"file": ("safe.zip", archive, "application/zip")},
    )
    workspace_id = import_response.json()["data"]["id"]

    response = await client.get(
        f"/api/workspaces/{workspace_id}/files/content",
        params={"path": "../outside.txt"},
    )

    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"]


async def test_workspace_file_api_rejects_reserved_names_and_unknown_encoding(client):
    archive = _zip_bytes({"safe.txt": "safe"})
    import_response = await client.post(
        "/api/workspaces/import",
        data={"name": "Reserved Workspace"},
        files={"file": ("reserved.zip", archive, "application/zip")},
    )
    workspace_id = import_response.json()["data"]["id"]

    reserved_response = await client.put(
        f"/api/workspaces/{workspace_id}/files/content",
        json={"path": "CON.txt", "content": "bad"},
    )
    assert reserved_response.status_code == 400
    assert "reserved Windows" in reserved_response.json()["detail"]

    encoding_response = await client.get(
        f"/api/workspaces/{workspace_id}/files/content",
        params={"path": "safe.txt", "encoding": "not-a-codec"},
    )
    assert encoding_response.status_code == 400
    assert "utf-8" in encoding_response.json()["detail"]


def test_agent_run_prefers_imported_project_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_module, "project_root", lambda: tmp_path)
    archive_path = tmp_path / "project.zip"
    archive_path.write_bytes(_zip_bytes({"README.md": "demo"}))
    workspace = WorkspaceStore().import_zip(
        archive_path,
        original_filename="project.zip",
        name="Project For Run",
    )

    assert _run_workspace(workspace.id) == Path(workspace.root_path).resolve()
    assert _run_workspace("missing-run") == (tmp_path / "workspace" / "runs" / "missing-run").resolve()
    assert _run_workspace(session_workspace_id("chat/main")) == (tmp_path / "workspace" / "sessions" / "chat-main").resolve()


def test_workspace_manifest_root_must_stay_under_projects_root(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_module, "project_root", lambda: tmp_path)
    store = WorkspaceStore()

    with pytest.raises(ValueError, match="outside managed projects root"):
        store._from_dict(
            {
                "id": "poisoned",
                "name": "Poisoned",
                "kind": "project",
                "source": "test",
                "root_path": str(tmp_path / "outside"),
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "metadata": {},
            }
        )
