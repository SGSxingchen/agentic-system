"""chatroom_get_goal — Spec 2 §3.2：读取当前 chatroom 的目标和元状态。

只读工具，无副作用。LM 调时优先从 ContextVar 拿当前 room_id 与 speaker，
所以 chatroom 外调用直接返回 error。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import get_current_room_id, get_current_speaker_name

logger = logging.getLogger(__name__)


_DESCRIPTION = """读取当前房间的 topic / goal / summary / 成员列表 / 你的身份。

什么时候用：
- 你刚被叫进房间，想知道这房间在干嘛
- 房间已经聊了一段时间，goal 可能变过，你不确定
- 决定"该不该插话/派人"前先看一眼 goal

什么时候不用：
- 想改 goal → 用 chatroom_set_goal 或 chatroom_update_goal
- 只想确认成员名 → 也可以直接用，但记得这些都会算一次工具调用

返回什么：
- topic：房间主题
- goal：当前主目标
- goal_revisions：历史改动次数
- goal_subgoals：当前未完成 / 已完成的子目标列表
- summary：房间已总结的过往
- members：当前成员列表（含动态成员）
- your_role：你在这房间叫什么名字（用于自我定位）
"""


class ChatroomGetGoalCapability(CapabilityBase):
    """只读读取房间状态。"""

    @property
    def name(self) -> str:
        return "chatroom_get_goal"

    @property
    def description(self) -> str:
        return _DESCRIPTION

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            returns="包含 topic/goal/summary/members/your_role 的字典；失败时返回 error",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        store = ChatroomStore()
        room = store.get_room(room_id)
        if not room:
            return {"error": f"chatroom '{room_id}' not found"}

        members: List[str] = list(room.get("members") or [])
        dynamic_names = [
            m.get("name") for m in (room.get("dynamic_members") or []) if m.get("name")
        ]
        all_members = list(dict.fromkeys(members + dynamic_names))

        speaker = get_current_speaker_name() or "unknown"

        return {
            "topic": room.get("topic") or "",
            "goal": room.get("goal") or "",
            "goal_revisions": len(room.get("goal_history") or []),
            "goal_subgoals": list(room.get("goal_subgoals") or []),
            "summary": room.get("summary") or "",
            "members": all_members,
            "your_role": speaker,
        }
