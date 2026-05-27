"""chatroom_dispatch — Spec 2 §5.3：让多个 Agent 并行加入房间发言。

替代旧版 ``host_directive`` JSON 文本协议（已删除，Task 8）。任何成员都能调，
不只 host_agent。错误信息直接返回 LM 让它自己读自己改（CC 范式 #2）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.chatroom_orchestrator import dispatch_speaking_task
from core.task import (
    get_current_parent_message_id,
    get_current_room_id,
    get_current_speaker_name,
)

logger = logging.getLogger(__name__)


_DESCRIPTION = """让多个 Agent 并行加入房间发言。任何成员都能调，不只是 host。

什么时候用（关键）：
- 想让多个 Agent 干不同的事 → 一次列多个 actions（这是默认！）
- 看到事情自己能解决就直接派 → 不需要请示别人
- @<name> 是简化形式：单 action 派单人

什么时候不用：
- 你只是想说话，没要派别人 → 直接说，不要调这个工具
- 想私下让子 Agent 算东西（不公开）→ 用 dispatch_agent（如果开了的话）

行为示例：
✅ 想让 reviewer 评一下 + coder 改一下
   → chatroom_dispatch(actions=[{agent:"reviewer", prompt:"..."}, {agent:"coder", prompt:"..."}])
   → 两人同时开始工作

❌ 先派 reviewer，等他说完再决定要不要派 coder
   → 浪费时间，把并行变串行

返回什么：
- dispatched: [{task_id, agent_name, status: "dispatched"}]
- failed: [{agent, reason}] 派不到的会列在这里，自己读自己改
- 不阻塞，被派的 Agent 会陆续在房间里发言
"""


async def _broadcast(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    try:
        from api.websocket.handlers import broadcast_chatroom_event  # type: ignore
    except Exception:  # pragma: no cover
        return
    try:
        await broadcast_chatroom_event(room_id, event_type, data)
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom_dispatch broadcast failed: %s", exc)


def _all_member_names(room: Dict[str, Any]) -> List[str]:
    members = list(room.get("members") or [])
    dynamic = [m.get("name") for m in (room.get("dynamic_members") or []) if m.get("name")]
    return list(dict.fromkeys([*members, *dynamic]))


class ChatroomDispatchCapability(CapabilityBase):
    """并行派发多个 Agent 加入房间发言。"""

    @property
    def name(self) -> str:
        return "chatroom_dispatch"

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
                    "actions": {
                        "type": "array",
                        "description": (
                            "要派发的 Agent 列表。"
                            "一次列多个能并行；列单个等同 @mention。"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {
                                    "type": "string",
                                    "description": "目标 Agent 名（必须是房间成员）",
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "可选：给该 Agent 的具体指令",
                                },
                            },
                            "required": ["agent"],
                        },
                        "minItems": 1,
                    },
                },
                "required": ["actions"],
            },
            returns="dispatched + failed 列表；只在房间内可用",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        actions = kwargs.get("actions")
        if not isinstance(actions, list) or not actions:
            return {"error": "actions must be a non-empty array"}

        store = ChatroomStore()
        room = store.get_room(room_id)
        if not room:
            return {"error": f"chatroom '{room_id}' not found"}

        valid_names = set(_all_member_names(room))
        speaker = get_current_speaker_name() or "unknown"
        parent_message_id = get_current_parent_message_id()

        dispatched: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for action in actions:
            if not isinstance(action, dict):
                failed.append({"agent": "(invalid)", "reason": "invalid_action_object"})
                continue
            agent_name = str(action.get("agent") or "").strip()
            if not agent_name:
                failed.append({"agent": "(empty)", "reason": "missing_agent"})
                continue
            if agent_name not in valid_names:
                failed.append({"agent": agent_name, "reason": "member_not_in_room"})
                continue

            prompt = action.get("prompt")
            if prompt is not None and not isinstance(prompt, str):
                prompt = str(prompt)

            ticket = dispatch_speaking_task(
                room_id,
                agent_name,
                prompt=prompt,
                parent_message_id=parent_message_id,
                store=store,
            )
            task_id = ticket.get("task_id")
            if ticket.get("error") or not task_id:
                failed.append(
                    {
                        "agent": agent_name,
                        "reason": ticket.get("error") or "dispatch_failed",
                        "ticket": ticket,
                    }
                )
                continue
            dispatched.append(
                {
                    "agent": agent_name,
                    "task_id": task_id,
                    "status": "dispatched",
                }
            )

        # 广播事件供前端 surface "Host 派发了 N 人"提示
        await _broadcast(
            room_id,
            "chatroom_dispatch_called",
            {
                "room_id": room_id,
                "dispatcher": speaker,
                "dispatched_task_ids": [d["task_id"] for d in dispatched],
                "actions": [
                    {"agent": d["agent"], "task_id": d["task_id"]} for d in dispatched
                ],
                "failed": failed,
            },
        )

        return {"dispatched": dispatched, "failed": failed}
