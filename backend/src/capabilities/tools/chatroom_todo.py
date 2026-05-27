"""chatroom_todo — Spec 2 §9：房间内任务清单管理。

灵感来自 Claude Code 的 TodoWrite：让 LM 自己写计划、自己更新进度。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import get_current_room_id, get_current_speaker_name

logger = logging.getLogger(__name__)


_DESCRIPTION = """房间内任务清单管理。任意成员都能用。

什么时候用（关键）：
- 你看到一个事情有多个步骤，先 chatroom_todo create 把所有步骤写下来
- 你完成了一个子任务 → chatroom_todo complete <todo_id>
- 看不清现在该干啥 → chatroom_todo list 看清楚
- 子任务被外部依赖卡住 → chatroom_todo block + notes 记录原因

设计哲学：写下来你才不会忘。这跟你脑子里的 plan 不一样，所有人都能看到。

action 列表：
- create：批量创建 todos（todos: [{content, assignee?}]）
- update：改 content 或 assignee（todo_id 必填）
- complete：标 completed（todo_id 必填）
- block：标 blocked + 可选 notes（todo_id 必填）
- delete：删除（todo_id 必填）
- list：列出当前所有 todos
"""


async def _broadcast(room_id: str, event_type: str, data: Dict[str, Any]) -> None:
    try:
        from api.websocket.handlers import broadcast_chatroom_event  # type: ignore
    except Exception:  # pragma: no cover
        return
    try:
        await broadcast_chatroom_event(room_id, event_type, data)
    except Exception as exc:  # pragma: no cover
        logger.warning("chatroom_todo broadcast failed: %s", exc)


class ChatroomTodoCapability(CapabilityBase):
    """房间任务清单 CRUD。"""

    @property
    def name(self) -> str:
        return "chatroom_todo"

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
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "update",
                            "complete",
                            "block",
                            "delete",
                            "list",
                        ],
                    },
                    "todos": {
                        "type": "array",
                        "description": "create 时使用",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "assignee": {"type": "string"},
                            },
                            "required": ["content"],
                        },
                    },
                    "todo_id": {
                        "type": "string",
                        "description": "update / complete / block / delete 必填",
                    },
                    "content": {
                        "type": "string",
                        "description": "update 时新文本",
                    },
                    "assignee": {
                        "type": "string",
                        "description": "update 时新指派对象",
                    },
                    "notes": {
                        "type": "string",
                        "description": "block 时记录原因",
                    },
                },
                "required": ["action"],
            },
            returns="包含 ok / todos / todo / removed 等键的字典；失败时返回 error",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=4000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        action = str(kwargs.get("action") or "").strip()
        if not action:
            return {"error": "action is required"}

        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        store = ChatroomStore()
        room = store.get_room(room_id)
        if not room:
            return {"error": f"chatroom '{room_id}' not found"}

        speaker = get_current_speaker_name() or "unknown"

        if action == "list":
            return {"ok": True, "todos": store.list_todos(room_id)}

        if action == "create":
            todos_in = kwargs.get("todos")
            if not isinstance(todos_in, list) or not todos_in:
                return {"error": "todos must be a non-empty array for create"}
            created: List[Dict[str, Any]] = []
            for raw in todos_in:
                if not isinstance(raw, dict):
                    continue
                content = str(raw.get("content") or "").strip()
                if not content:
                    continue
                assignee = raw.get("assignee")
                created_todo = store.add_todo(
                    room_id,
                    content,
                    assignee=str(assignee).strip() if isinstance(assignee, str) else None,
                )
                if created_todo:
                    created.append(created_todo)
            if not created:
                return {"error": "no valid todos created"}
            await _broadcast(
                room_id,
                "chatroom_todo_added",
                {"room_id": room_id, "todos": created, "by": speaker},
            )
            return {"ok": True, "todos": created}

        # 以下 action 都需要 todo_id
        todo_id = str(kwargs.get("todo_id") or "").strip()
        if not todo_id:
            return {"error": f"todo_id is required for action={action}"}

        if action == "complete":
            updated = store.update_todo(room_id, todo_id, status="completed")
            if not updated:
                return {"error": f"todo '{todo_id}' not found"}
            await _broadcast(
                room_id,
                "chatroom_todo_completed",
                {"room_id": room_id, "todo_id": todo_id, "todo": updated, "by": speaker},
            )
            return {"ok": True, "todo": updated}

        if action == "block":
            notes = kwargs.get("notes")
            patch: Dict[str, Any] = {"status": "blocked"}
            if isinstance(notes, str) and notes.strip():
                patch["notes"] = notes.strip()
            updated = store.update_todo(room_id, todo_id, **patch)
            if not updated:
                return {"error": f"todo '{todo_id}' not found"}
            await _broadcast(
                room_id,
                "chatroom_todo_updated",
                {"room_id": room_id, "todo": updated, "by": speaker},
            )
            return {"ok": True, "todo": updated}

        if action == "update":
            patch: Dict[str, Any] = {}
            for key in ("content", "assignee", "notes", "status"):
                val = kwargs.get(key)
                if isinstance(val, str) and val.strip():
                    patch[key] = val.strip()
            if not patch:
                return {"error": "update requires at least one of content/assignee/notes/status"}
            updated = store.update_todo(room_id, todo_id, **patch)
            if not updated:
                return {"error": f"todo '{todo_id}' not found"}
            await _broadcast(
                room_id,
                "chatroom_todo_updated",
                {"room_id": room_id, "todo": updated, "by": speaker},
            )
            return {"ok": True, "todo": updated}

        if action == "delete":
            ok = store.delete_todo(room_id, todo_id)
            if not ok:
                return {"error": f"todo '{todo_id}' not found"}
            await _broadcast(
                room_id,
                "chatroom_todo_deleted",
                {"room_id": room_id, "todo_id": todo_id, "by": speaker},
            )
            return {"ok": True, "removed": todo_id}

        return {"error": f"unknown action '{action}'"}
