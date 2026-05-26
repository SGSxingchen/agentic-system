"""Chatroom routes (multi-agent group chat).

Phase 1 surface — REST only. Uses ``ChatroomStore`` for persistence and the
existing ``CapabilityRegistry`` to drive a single Agent reply per ``invoke``
call (blocking). Phase 2 will turn ``invoke`` into a non-blocking speaking task
with WebSocket streaming and relay dispatch.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from core.chatroom import ChatroomStore, build_room_context, parse_mentions

from ..dependencies import get_agent_registry, get_capability_registry
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
    """Append a user message; parse mentions only (Phase 1 dispatches nothing)."""

    room = _ensure_room(room_id)
    valid_names = _all_member_names(room)
    mentions = parse_mentions(req.content, valid_names)

    message = _store().add_message(
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

    return APIResponse(
        status="ok",
        data={
            "message": message,
            "mentions": mentions,
            # Phase 2 will attach dispatched_tasks; expose key now to keep schema stable
            "dispatched_tasks": [],
        },
    )


# ─── 召唤 Agent 发言（Phase 1: 阻塞）─────────────────────


@router.post("/{room_id}/invoke", response_model=APIResponse)
async def invoke_chatroom_agent(
    room_id: str,
    req: ChatroomInvokeRequest,
) -> APIResponse:
    """Blocking single-shot agent reply. Phase 2 swaps this for a speaking task."""

    store = _store()
    room = _ensure_room(room_id)

    valid_names = _all_member_names(room)
    if req.agent_name not in valid_names:
        # 写一条 failed 占位消息，便于前端看到拒绝原因
        store.add_message(
            room_id,
            {
                "sender": f"agent:{req.agent_name}",
                "content": f"成员 {req.agent_name} 不在房间里",
                "status": "failed",
                "meta": {"error": "member_not_in_room"},
            },
        )
        raise HTTPException(
            status_code=400,
            detail=f"agent '{req.agent_name}' is not a member of this chatroom",
        )

    cap_registry = get_capability_registry()
    if cap_registry is None:
        raise HTTPException(
            status_code=503,
            detail="capability registry not initialised",
        )
    if not cap_registry.get(req.agent_name):
        store.add_message(
            room_id,
            {
                "sender": f"agent:{req.agent_name}",
                "content": f"成员 {req.agent_name} 已失效（未在 capability registry 注册）",
                "status": "failed",
                "meta": {"error": "agent_not_registered"},
            },
        )
        raise HTTPException(status_code=404, detail=f"agent '{req.agent_name}' not registered")

    # 拼上下文
    context_messages = build_room_context(room, req.agent_name)
    payload: Dict[str, Any] = {
        "messages": context_messages,
        "message": req.prompt or "请发言",
    }
    if room.get("workspace_id"):
        payload["workspace_id"] = room["workspace_id"]

    try:
        result = await cap_registry.execute(req.agent_name, **payload)
    except Exception as exc:  # noqa: BLE001 — 兜底捕获后写 failed 消息
        logger.exception("chatroom invoke failed for agent=%s", req.agent_name)
        message = store.add_message(
            room_id,
            {
                "sender": f"agent:{req.agent_name}",
                "content": f"调用失败：{exc}",
                "status": "failed",
                "meta": {"error": str(exc), "exception_type": type(exc).__name__},
            },
        )
        return APIResponse(
            status="error",
            message=str(exc),
            data={"message": message, "dispatched_tasks": []},
        )

    reply_text = _coerce_reply_text(result)
    mentions = parse_mentions(reply_text, _all_member_names(room))
    meta: Dict[str, Any] = {}
    if isinstance(result, dict):
        for key in ("usage", "elapsed_ms", "metrics"):
            if key in result:
                meta[key] = result[key]

    message = store.add_message(
        room_id,
        {
            "sender": f"agent:{req.agent_name}",
            "content": reply_text,
            "mentions": mentions,
            "status": "done",
            "meta": meta,
        },
    )
    return APIResponse(
        status="ok",
        data={
            "message": message,
            # Phase 2 接力派发；Phase 1 先返回空数组占位
            "dispatched_tasks": [],
        },
    )


# ─── 取消（Phase 1 桩）────────────────────────────────────


@router.post("/{room_id}/cancel", response_model=APIResponse)
async def cancel_chatroom_tasks(room_id: str) -> APIResponse:
    """Cancel all in-flight speaking tasks (Phase 2 hooks this up)."""

    _ensure_room(room_id)
    return APIResponse(status="ok", data={"cancelled": 0})


# ─── 内部 ─────────────────────────────────────────────────


def _coerce_reply_text(result: Any) -> str:
    """把 cap_registry.execute 的返回值压成一段文本，给消息正文用。

    Agent.run 返回 dict：``{"response": str, ...}``（text 模式）或
    解析后的 JSON dict（json 模式）。我们尽量取 ``response`` 字段，
    取不到就回退到 ``raw_response`` 或整个 dict 的 JSON 串，避免空消息。
    """

    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("response", "raw_response", "content", "text", "answer"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        # JSON 模式且无 response：序列化整个 dict 兜底
        try:
            import json

            return json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(result)
    return str(result)
