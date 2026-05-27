"""chatroom_update_goal — Spec 2 §3.2：增量更新房间目标和子目标。

不同于覆盖式 chatroom_set_goal：本工具支持 add_subgoal / mark_done /
remove_subgoal 三种增量操作，外加 revise 原子替换主 goal（旧 goal 入 history）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import get_current_room_id, get_current_speaker_name

logger = logging.getLogger(__name__)


_DESCRIPTION = """增量更新房间目标 — 在原 goal 上加子目标 / 标记完成 / 修订 / 移除。
不像 chatroom_set_goal 那样整段覆盖。

什么时候用：
- 把"做完一份评审报告"加到现有目标 → operation=add_subgoal, content="..."
- 标记"已完成代码生成"子目标 → operation=mark_done, subgoal_id="..."
- 微调主 goal 措辞 → operation=revise, content="完整新目标"
- 子目标作废 → operation=remove_subgoal, subgoal_id="..."

什么时候 *不* 用：
- goal 整体方向变了（不是微调）→ 也可以 revise，但 chatroom_set_goal 也行
- 只是想问 goal 是什么 → 用 chatroom_get_goal

返回什么：
- 成功：{"ok": True, "subgoal": ...}（add/mark_done）或 {"ok": True, "goal": ...}（revise）
- 失败：{"error": "..."}（参数缺失 / 未找到子目标 / 房间外调用）
"""


async def _broadcast(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    try:
        from api.websocket.handlers import broadcast_chatroom_event  # type: ignore
    except Exception:  # pragma: no cover
        return
    try:
        await broadcast_chatroom_event(room_id, event_type, data)
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom_update_goal broadcast failed: %s", exc)


class ChatroomUpdateGoalCapability(CapabilityBase):
    """增量更新房间 goal / 子目标。"""

    @property
    def name(self) -> str:
        return "chatroom_update_goal"

    @property
    def description(self) -> str:
        return _DESCRIPTION

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add_subgoal", "mark_done", "remove_subgoal", "revise"],
                        "description": "操作类型",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "add_subgoal 时为子目标文本；"
                            "revise 时为完整新主 goal。"
                        ),
                    },
                    "subgoal_id": {
                        "type": "string",
                        "description": "mark_done / remove_subgoal 时必填",
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选：变更原因",
                    },
                },
                "required": ["operation"],
            },
            returns="包含 ok 与具体子目标 / goal 的字典；失败时返回 error",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=2000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = str(kwargs.get("operation") or "").strip()
        if not operation:
            return {"error": "operation is required"}

        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        speaker = get_current_speaker_name() or "unknown"
        store = ChatroomStore()

        content = kwargs.get("content")
        subgoal_id = kwargs.get("subgoal_id")
        if isinstance(content, str):
            content = content.strip()
        if isinstance(subgoal_id, str):
            subgoal_id = subgoal_id.strip()

        result = store.apply_goal_subgoal_op(
            room_id,
            operation,
            content=content if isinstance(content, str) else None,
            subgoal_id=subgoal_id if isinstance(subgoal_id, str) else None,
            by=speaker,
        )
        if "error" in result:
            return result

        # 广播对应事件
        if operation == "add_subgoal":
            await _broadcast(
                room_id,
                "chatroom_goal_subgoal_added",
                {"room_id": room_id, "subgoal": result.get("subgoal"), "by": speaker},
            )
            return {"ok": True, "subgoal": result.get("subgoal")}
        if operation == "mark_done":
            await _broadcast(
                room_id,
                "chatroom_goal_subgoal_done",
                {
                    "room_id": room_id,
                    "subgoal_id": subgoal_id,
                    "subgoal": result.get("subgoal"),
                    "by": speaker,
                },
            )
            return {"ok": True, "subgoal": result.get("subgoal")}
        if operation == "remove_subgoal":
            await _broadcast(
                room_id,
                "chatroom_goal_subgoal_removed",
                {"room_id": room_id, "subgoal_id": subgoal_id, "by": speaker},
            )
            return {"ok": True, "removed": result.get("removed")}
        if operation == "revise":
            await _broadcast(
                room_id,
                "chatroom_goal_updated",
                {"room_id": room_id, "goal": result.get("goal"), "by": speaker},
            )
            return {"ok": True, "goal": result.get("goal")}

        return {"error": f"unknown operation '{operation}'"}
