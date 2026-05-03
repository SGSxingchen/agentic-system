"""Artifact routes for Claude-like generated previews and downloads."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from core.artifacts import ArtifactStore, is_text_mime

from ..schemas import APIResponse, ArtifactCreateRequest

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _store() -> ArtifactStore:
    return ArtifactStore()


@router.get("", response_model=APIResponse)
async def list_artifacts(
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> APIResponse:
    return APIResponse(status="ok", data=_store().list_artifacts(session_id=session_id, limit=limit))


@router.post("", response_model=APIResponse)
async def create_artifact(req: ArtifactCreateRequest) -> APIResponse:
    try:
        artifact = _store().create_artifact(**req.model_dump(exclude_none=True))
    except Exception as exc:
        return APIResponse(status="error", message=f"create artifact failed: {exc}")
    return APIResponse(status="ok", data=artifact)


@router.get("/{artifact_id}", response_model=APIResponse)
async def get_artifact(artifact_id: str) -> APIResponse:
    artifact = _store().get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    return APIResponse(status="ok", data=artifact)


@router.get("/{artifact_id}/content", response_model=APIResponse)
async def get_artifact_content(artifact_id: str) -> APIResponse:
    store = _store()
    artifact = store.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    if not is_text_mime(artifact.get("mime_type", "")) and artifact.get("kind") != "markdown" and artifact.get("kind") != "code":
        return APIResponse(status="error", message="artifact content is binary; use download/open url")
    content = store.read_text(artifact_id)
    if content is None:
        raise HTTPException(status_code=404, detail="artifact content not found")
    return APIResponse(status="ok", data={"artifact": artifact, "content": content})


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str) -> FileResponse:
    artifact = _store().get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    path = _store().get_file_path(artifact)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file not found")
    return FileResponse(path, media_type=artifact.get("mime_type"), filename=artifact.get("filename"))


@router.get("/{artifact_id}/open")
async def open_artifact(artifact_id: str) -> Response:
    artifact = _store().get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    path = _store().get_file_path(artifact)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file not found")
    headers = {
        "Content-Disposition": f"inline; filename=\"{artifact.get('filename')}\"",
        # Opening an artifact is intentionally safer than embedding it in the app:
        # it cannot execute scripts against the main frontend origin. Interactive
        # HTML previews still use the ChatPanel sandboxed iframe.
        "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data: blob:; style-src 'unsafe-inline';",
    }
    return Response(content=path.read_bytes(), media_type=artifact.get("mime_type"), headers=headers)


@router.delete("/{artifact_id}", response_model=APIResponse)
async def delete_artifact(artifact_id: str) -> APIResponse:
    if not _store().delete_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="artifact not found")
    return APIResponse(status="ok")
