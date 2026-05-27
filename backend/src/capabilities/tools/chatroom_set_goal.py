"""chatroom_set_goal — Phase 4：更新当前 chatroom 的主要目标。"""
from __future__ import annotations

import logging
from typing import Any, Dict

from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import get_current_room_id, get_current_speaker_name

logger = logging.getLogger(__name__)


async def _broadcast(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    try:
        from api.websocket.handlers import broadcast_chatroom_event  # type: ignore
    except Exception:  # pragma: no cover
        return
    try:
        await broadcast_chatroom_event(room_id, event_type, data)
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom_set_goal broadcast failed: %s", exc)


class ChatroomSetGoalCapability(CapabilityBase):
    """更新房间 goal 并把旧 goal 推入 goal_history。"""

    @property
    def name(self) -> str:
        return "chatroom_set_goal"

    @property
    def description(self) -> str:
        return (
            "聊天室目标更新工具：替换当前房间的主要目标；只能在 chatroom 发言任务内使用。"
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "新的房间主要目标（单行）",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选：变更原因，会落进 goal_history",
                    },
                },
                "required": ["goal"],
            },
            returns="包含 ok / goal 的字典；失败时返回 error",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=2000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        goal = str(kwargs.get("goal") or "").strip()
        if not goal:
            return {"error": "goal is required"}
        reason = str(kwargs.get("reason") or "").strip() or None

        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        speaker = get_current_speaker_name() or "system"
        store = ChatroomStore()
        updated = store.set_room_goal(room_id, goal, set_by=speaker, reason=reason)
        if not updated:
            return {"error": f"chatroom '{room_id}' not found"}

        suffix = f"，原因：{reason}" if reason else ""
        store.add_message(
            room_id,
            {
                "sender": "system",
                "content": f"目标已更新为：{goal}（by {speaker}{suffix}）",
                "status": "done",
                "meta": {"event": "goal_updated", "by": speaker, "goal": goal},
            },
        )

        await _broadcast(
            room_id,
            "chatroom_goal_updated",
            {
                "room_id": room_id,
                "goal": goal,
                "by": speaker,
                "reason": reason,
            },
        )

        return {"ok": True, "goal": goal}
