"""Chatroom routes (multi-agent group chat).

Phase 2 surface — REST + non-blocking task dispatch. The blocking
single-shot ``invoke`` of Phase 1 has been replaced by a speaking task that
streams events to subscribed websockets via
``broadcast_chatroom_event``. Mentioned agents are auto-dispatched
(``dispatch_speaking_task``) and the auto-host setting is honoured.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from core.chatroom import ChatroomStore, parse_mentions
from core.chatroom_orchestrator import dispatch_speaking_task
from core.task import TaskStatus

from ..dependencies import get_capability_registry, get_task_registry
from ..schemas import (
    APIResponse,
    ChatroomCreateRequest,
    ChatroomInvokeRequest,
    ChatroomMessageCreateRequest,
    ChatroomUpdateRequest,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chatrooms", tags=["chatroom"])


def _store() -> ChatroomStore:
    return ChatroomStore()


def _all_member_names(room: Dict[str, Any]) -> List[str]:
    members = list(room.get("members") or [])
    dynamic = [m.get("name") for m in (room.get("dynamic_members") or []) if m.get("name")]
    return list(dict.fromkeys([*members, *dynamic]))


def _ensure_room(room_id: str) -> Dict[str, Any]:
    room = _store().get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="chatroom not found")
    return room


# ─── 房间 CRUD ────────────────────────────────────────────


@router.get("", response_model=APIResponse)
async def list_chatrooms() -> APIResponse:
    """List room summaries."""

    return APIResponse(status="ok", data=_store().list_rooms())


@router.post("", response_model=APIResponse)
async def create_chatroom(req: ChatroomCreateRequest) -> APIResponse:
    """Create a new chatroom."""

    dynamic_members = [item.model_dump() for item in req.dynamic_members]
    room = _store().create_room(
        title=req.title,
        topic=req.topic,
        goal=req.goal,
        members=req.members,
        dynamic_members=dynamic_members,
        workspace_id=req.workspace_id,
        settings=req.settings,
    )
    return APIResponse(status="ok", data=room)


@router.get("/{room_id}", response_model=APIResponse)
async def get_chatroom(room_id: str) -> APIResponse:
    """Return a full chatroom (including messages)."""

    return APIResponse(status="ok", data=_ensure_room(room_id))


@router.put("/{room_id}", response_model=APIResponse)
async def update_chatroom(room_id: str, req: ChatroomUpdateRequest) -> APIResponse:
    """Update room metadata."""

    payload: Dict[str, Any] = {}
    fields = req.model_fields_set
    if "title" in fields and req.title is not None:
        payload["title"] = req.title
    if "topic" in fields and req.topic is not None:
        payload["topic"] = req.topic
    if "goal" in fields:
        payload["goal"] = req.goal
    if "members" in fields and req.members is not None:
        payload["members"] = req.members
    if "dynamic_members" in fields and req.dynamic_members is not None:
        payload["dynamic_members"] = [item.model_dump() for item in req.dynamic_members]
    if "workspace_id" in fields:
        payload["workspace_id"] = req.workspace_id
    if "settings" in fields and req.settings is not None:
        payload["settings"] = req.settings

    room = _store().update_room(room_id, **payload)
    if not room:
        raise HTTPException(status_code=404, detail="chatroom not found")
    return APIResponse(status="ok", data=room)


@router.delete("/{room_id}", response_model=APIResponse)
async def delete_chatroom(room_id: str) -> APIResponse:
    """Delete a chatroom (Phase 1: only the JSON file)."""

    deleted = _store().delete_room(room_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="chatroom not found")
    return APIResponse(status="ok")


# ─── 消息 ────────────────────────────────────────────────


@router.get("/{room_id}/messages", response_model=APIResponse)
async def list_chatroom_messages(
    room_id: str,
    since: Optional[str] = None,
) -> APIResponse:
    """Incrementally fetch messages (``?since=<msg_id>`` exclusive)."""

    # 房间存在性显式校验，给 404 而非空数组
    _ensure_room(room_id)
    messages = _store().list_messages(room_id, since=since)
    return APIResponse(status="ok", data={"messages": messages})


@router.post("/{room_id}/messages", response_model=APIResponse)
async def post_chatroom_user_message(
    room_id: str,
    req: ChatroomMessageCreateRequest,
) -> APIResponse:
    """Append a user message and dispatch any mentioned agents.

    Phase 2 wires mentions to ``dispatch_speaking_task`` so each mentioned
    member gets its own ``AGENT_SPEAK`` task running in the background.
    The ``auto_host`` setting falls back to the host agent when no mention
    targets an existing member.
    """

    store = _store()
    room = _ensure_room(room_id)
    valid_names = _all_member_names(room)
    mentions = parse_mentions(req.content, valid_names)

    message = store.add_message(
        room_id,
        {
            "sender": "user",
            "content": req.content,
            "mentions": mentions,
            "status": "done",
        },
    )
    if not message:
        raise HTTPException(status_code=404, detail="chatroom not found")

    dispatched: List[Dict[str, Any]] = []
    for target in mentions:
        ticket = dispatch_speaking_task(
            room_id,
            target,
            parent_message_id=message["id"],
            store=store,
        )
        dispatched.append(ticket)

    if not mentions:
        settings = room.get("settings") or {}
        if bool(settings.get("auto_host")):
            host_agent = str(settings.get("host_agent") or "planner").strip()
            if host_agent and host_agent in valid_names:
                ticket = dispatch_speaking_task(
                    room_id,
                    host_agent,
                    parent_message_id=message["id"],
                    store=store,
                )
                dispatched.append(ticket)

    return APIResponse(
        status="ok",
        data={
            "message": message,
            "mentions": mentions,
            "dispatched_tasks": dispatched,
        },
    )


# ─── 召唤 Agent 发言（Phase 2: 非阻塞）─────────────────────


@router.post("/{room_id}/invoke", response_model=APIResponse)
async def invoke_chatroom_agent(
    room_id: str,
    req: ChatroomInvokeRequest,
) -> APIResponse:
    """Dispatch a speaking task for ``agent_name``; returns immediately.

    The actual reply streams through the chatroom websocket channel; clients
    should subscribe via ``{event_type: "subscribe", channel: "chatroom:<id>"}``
    to receive ``chatroom_agent_thinking`` / ``chatroom_message_done``.
    """

    _ensure_room(room_id)
    ticket = dispatch_speaking_task(
        room_id,
        req.agent_name,
        prompt=req.prompt,
    )
    if ticket.get("error") == "member_not_in_room":
        raise HTTPException(
            status_code=400,
            detail=f"agent '{req.agent_name}' is not a member of this chatroom",
        )
    if ticket.get("error") == "agent_not_registered":
        raise HTTPException(status_code=404, detail=f"agent '{req.agent_name}' not registered")
    if ticket.get("error"):
        return APIResponse(
            status="error",
            message=str(ticket.get("error")),
            data=ticket,
        )

    return APIResponse(status="ok", data=ticket)


# ─── 取消 ─────────────────────────────────────────────────


@router.post("/{room_id}/cancel", response_model=APIResponse)
async def cancel_chatroom_tasks(room_id: str) -> APIResponse:
    """Cancel all in-flight speaking tasks for the room."""

    room = _ensure_room(room_id)
    task_registry = get_task_registry()
    if task_registry is None:
        return APIResponse(status="ok", data={"cancelled": 0})

    cancelled = 0
    in_flight = {"pending", "streaming"}
    for msg in (room.get("messages") or []):
        status = str(msg.get("status") or "")
        task_id = msg.get("task_id")
        if status in in_flight and task_id:
            if task_registry.kill(task_id):
                cancelled += 1
    return APIResponse(status="ok", data={"cancelled": cancelled})
