"""chatroom_invite — Phase 4：把已注册 Agent 邀请到当前房间。

仅在 chatroom speaking task 内可用：通过 ContextVar ``current_room_id`` 取
当前房间。``current_speaker_name`` 用来在 system 消息里署名邀请人。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import get_current_room_id, get_current_speaker_name

logger = logging.getLogger(__name__)


def _get_capability_registry():
    try:
        from api.dependencies import get_capability_registry as _g  # type: ignore
        return _g()
    except Exception:
        return None


def _get_agent_registry():
    try:
        from api.dependencies import get_agent_registry as _g  # type: ignore
        return _g()
    except Exception:
        return None


async def _broadcast(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    try:
        from api.websocket.handlers import broadcast_chatroom_event  # type: ignore
    except Exception:  # pragma: no cover
        return
    try:
        await broadcast_chatroom_event(room_id, event_type, data)
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom_invite broadcast failed: %s", exc)


def _is_agent_known(agent_name: str) -> bool:
    """Whether the target agent is reachable via either registry."""

    cap_registry = _get_capability_registry()
    if cap_registry is not None and cap_registry.get(agent_name) is not None:
        return True
    agent_registry = _get_agent_registry()
    if agent_registry is not None and agent_registry.get(agent_name) is not None:
        return True
    return False


class ChatroomInviteCapability(CapabilityBase):
    """把已注册的 Agent 邀请到当前 chatroom。"""

    @property
    def name(self) -> str:
        return "chatroom_invite"

    @property
    def description(self) -> str:
        return (
            "聊天室邀请工具：把已注册 Agent 加入当前房间；只能在 chatroom 发言任务内使用。"
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "要邀请的 Agent 名（必须在 AgentRegistry 或 CapabilityRegistry 已注册）",
                    },
                },
                "required": ["agent_name"],
            },
            returns="包含 ok / agent_name / members_count 的字典；失败时返回 error",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=2000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        agent_name = str(kwargs.get("agent_name") or "").strip()
        if not agent_name:
            return {"error": "agent_name is required"}

        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        store = ChatroomStore()
        room = store.get_room(room_id)
        if not room:
            return {"error": f"chatroom '{room_id}' not found"}

        settings = room.get("settings") or {}
        if settings.get("allow_agent_invite") is False:
            return {"error": "this room disallows agent invites"}

        if not _is_agent_known(agent_name):
            return {"error": f"agent '{agent_name}' not registered"}

        members: List[str] = list(room.get("members") or [])
        dynamic_names = [
            m.get("name") for m in (room.get("dynamic_members") or []) if m.get("name")
        ]
        if agent_name in members or agent_name in dynamic_names:
            return {"error": "agent already in room"}

        try:
            max_members = int(settings.get("max_members", 20))
        except (TypeError, ValueError):
            max_members = 20
        total = len(members) + len(dynamic_names)
        if total >= max_members:
            return {"error": "room member limit reached"}

        new_members = list(members) + [agent_name]
        updated = store.update_room(room_id, members=new_members)
        if not updated:
            return {"error": "failed to update room"}

        speaker = get_current_speaker_name() or "system"
        store.add_message(
            room_id,
            {
                "sender": "system",
                "content": f"{speaker} 邀请 {agent_name} 加入房间",
                "status": "done",
                "meta": {"event": "member_added", "by": speaker, "agent_name": agent_name},
            },
        )

        await _broadcast(
            room_id,
            "chatroom_member_added",
            {
                "room_id": room_id,
                "member": {"name": agent_name, "kind": "static"},
                "by": speaker,
            },
        )

        return {
            "ok": True,
            "agent_name": agent_name,
            "members_count": len(new_members) + len(dynamic_names),
        }
