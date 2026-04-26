"""Chat session routes.

These routes persist multiple chat pages so the assistant has visible,
switchable conversation history in the web UI.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.chat_history import ChatHistoryStore

from ..schemas import (
    APIResponse,
    ChatMessageCreateRequest,
    ChatSessionCreateRequest,
    ChatSessionUpdateRequest,
)

router = APIRouter(prefix="/api/chat-sessions", tags=["chat"])


def _store() -> ChatHistoryStore:
    return ChatHistoryStore()


@router.get("", response_model=APIResponse)
async def list_chat_sessions() -> APIResponse:
    """List chat session summaries."""

    return APIResponse(status="ok", data=_store().list_sessions())


@router.post("", response_model=APIResponse)
async def create_chat_session(req: ChatSessionCreateRequest) -> APIResponse:
    """Create a new chat page."""

    session = _store().create_session(req.title)
    return APIResponse(status="ok", data=session)


@router.get("/{session_id}", response_model=APIResponse)
async def get_chat_session(session_id: str) -> APIResponse:
    """Return a full chat session including messages."""

    session = _store().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="chat session not found")
    return APIResponse(status="ok", data=session)


@router.put("/{session_id}", response_model=APIResponse)
async def update_chat_session(
    session_id: str,
    req: ChatSessionUpdateRequest,
) -> APIResponse:
    """Update chat session metadata."""

    session = _store().update_session(session_id, title=req.title)
    if not session:
        raise HTTPException(status_code=404, detail="chat session not found")
    return APIResponse(status="ok", data=session)


@router.delete("/{session_id}", response_model=APIResponse)
async def delete_chat_session(session_id: str) -> APIResponse:
    """Delete a chat session page."""

    deleted = _store().delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="chat session not found")
    return APIResponse(status="ok")


@router.post("/{session_id}/messages", response_model=APIResponse)
async def add_chat_message(
    session_id: str,
    req: ChatMessageCreateRequest,
) -> APIResponse:
    """Append one message to a chat session."""

    session = _store().add_message(session_id, req.model_dump(exclude_none=True))
    if not session:
        raise HTTPException(status_code=404, detail="chat session not found")
    return APIResponse(status="ok", data=session)
