"""chatroom_create_agent — Phase 4：运行时创造一个新 Agent 并加入当前房间。

实现细节：
- 基于 ``base_agent`` 找一个已注册 Agent（默认 "generic"），克隆其 LLM 客户端、
  工具列表、output_format 等，**用 role_prompt 作为新 system_prompt**。
- 注册到 AgentRegistry + 包成 AgentCapability 注册到 CapabilityRegistry，
  让其他成员 / orchestrator 都能查得到。
- dynamic_members 持久化到房间 JSON；后端重启时由 ``rebuild_chatroom_dynamic_agents``
  重新构造（main.py reload_agents 末尾调用）。
- 单 task 上限 2：使用 ``current_create_counter`` ContextVar（list[int] 容器）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.capability.agent_adapter import AgentCapability
from core.capability.base import CapabilityBase, CapabilitySchema
from core.chatroom import ChatroomStore
from core.task import (
    get_current_create_counter,
    get_current_room_id,
    get_current_speaker_name,
)

logger = logging.getLogger(__name__)

_MAX_CREATE_PER_TASK = 2


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
        logger.warning("chatroom_create_agent broadcast failed: %s", exc)


def _build_dynamic_agent(
    name: str,
    role_prompt: str,
    base_agent_name: str,
):
    """Clone a base Agent into a new one with overridden system prompt.

    Returns the newly constructed ``Agent`` instance, or ``None`` when the
    base agent cannot be located.
    """

    agent_registry = _get_agent_registry()
    if agent_registry is None:
        return None
    base = agent_registry.get(base_agent_name)
    if base is None:
        return None

    # 延迟导入避免循环
    from core.agent.agent import Agent  # type: ignore

    return Agent(
        name=name,
        llm_client=base.llm,
        system_prompt=role_prompt,
        tools=list(getattr(base, "_tools", []) or []),
        output_format=getattr(base, "_output_format", "text"),
        max_iterations=getattr(base, "_max_iterations", 10),
        description=f"动态成员（基于 {base_agent_name}）",
        token_budget=getattr(base, "_token_budget", None),
        token_budget_nudge_threshold=getattr(
            base, "_token_budget_nudge_threshold", 0.85
        ),
        runtime_config={
            **(getattr(base, "_runtime_config", {}) or {}),
            "dynamic_origin": {
                "base_agent": base_agent_name,
                "role_prompt": role_prompt,
            },
        },
    )


class ChatroomCreateAgentCapability(CapabilityBase):
    """运行时创建并注册一个新 Agent，自动加入当前 chatroom。"""

    @property
    def name(self) -> str:
        return "chatroom_create_agent"

    @property
    def description(self) -> str:
        return (
            "聊天室动态成员创建工具：基于已注册 base_agent 复制一个新 Agent，加入当前房间；"
            "只能在 chatroom 发言任务内使用。"
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "新 Agent 的名字（不能与已有 Agent / 成员重名）",
                    },
                    "role_prompt": {
                        "type": "string",
                        "description": "新 Agent 的角色提示词（替换其 system_prompt）",
                    },
                    "base_agent": {
                        "type": "string",
                        "description": "可选：以哪一个已注册 Agent 为基底，默认 'generic'",
                        "default": "generic",
                    },
                },
                "required": ["name", "role_prompt"],
            },
            returns="包含 ok / name / base_agent 的字典；失败时返回 error",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=2000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        new_name = str(kwargs.get("name") or "").strip()
        role_prompt = str(kwargs.get("role_prompt") or "").strip()
        base_agent_name = str(kwargs.get("base_agent") or "").strip() or "generic"

        if not new_name:
            return {"error": "name is required"}
        if not role_prompt:
            return {"error": "role_prompt is required"}

        room_id = get_current_room_id()
        if not room_id:
            return {"error": "must be called inside a chatroom speaking task"}

        # 单 task 上限校验
        counter = get_current_create_counter()
        if counter is not None and counter and counter[0] >= _MAX_CREATE_PER_TASK:
            return {
                "error": (
                    f"chatroom_create_agent reached per-task limit "
                    f"({_MAX_CREATE_PER_TASK}) in this speaking task"
                )
            }

        store = ChatroomStore()
        room = store.get_room(room_id)
        if not room:
            return {"error": f"chatroom '{room_id}' not found"}

        cap_registry = _get_capability_registry()
        agent_registry = _get_agent_registry()

        # 重名校验（cap_registry / agent_registry / 当前 room 已有成员）
        members: List[str] = list(room.get("members") or [])
        dynamic_existing: List[Dict[str, Any]] = list(room.get("dynamic_members") or [])
        existing_names = set(members) | {
            m.get("name") for m in dynamic_existing if m.get("name")
        }
        if new_name in existing_names:
            return {"error": f"agent name '{new_name}' already exists in this room"}
        if cap_registry is not None and cap_registry.get(new_name) is not None:
            return {"error": f"agent name '{new_name}' already registered in capability registry"}
        if agent_registry is not None and agent_registry.get(new_name) is not None:
            return {"error": f"agent name '{new_name}' already registered in agent registry"}

        # 总成员上限校验
        settings = room.get("settings") or {}
        try:
            max_members = int(settings.get("max_members", 20))
        except (TypeError, ValueError):
            max_members = 20
        if len(members) + len(dynamic_existing) >= max_members:
            return {"error": "room member limit reached"}

        # 实例化新 Agent
        new_agent = _build_dynamic_agent(new_name, role_prompt, base_agent_name)
        if new_agent is None:
            return {"error": f"base_agent '{base_agent_name}' is not registered"}

        # 注册到 AgentRegistry + CapabilityRegistry
        if agent_registry is not None:
            agent_registry.register(new_agent)
        if cap_registry is not None:
            cap_registry.register_native(AgentCapability(new_agent, None))

        # 写回 dynamic_members + members（让 mention 解析认可）
        new_dynamic = list(dynamic_existing) + [
            {
                "name": new_name,
                "role_prompt": role_prompt,
                "base_agent": base_agent_name,
            }
        ]
        new_members = list(members) + [new_name]
        store.update_room(
            room_id,
            members=new_members,
            dynamic_members=new_dynamic,
        )

        # 计数器递增
        if counter is not None:
            counter[0] = (counter[0] if counter else 0) + 1

        # System 消息 + 广播
        speaker = get_current_speaker_name() or "system"
        store.add_message(
            room_id,
            {
                "sender": "system",
                "content": f"{speaker} 创建了新成员 @{new_name}（基于 {base_agent_name}）",
                "status": "done",
                "meta": {
                    "event": "member_added",
                    "by": speaker,
                    "agent_name": new_name,
                    "kind": "dynamic",
                    "base_agent": base_agent_name,
                },
            },
        )
        await _broadcast(
            room_id,
            "chatroom_member_added",
            {
                "room_id": room_id,
                "member": {
                    "name": new_name,
                    "kind": "dynamic",
                    "base_agent": base_agent_name,
                    "role_prompt": role_prompt,
                },
                "by": speaker,
            },
        )

        return {
            "ok": True,
            "name": new_name,
            "base_agent": base_agent_name,
        }


# ─── 重启重建 dynamic_members ─────────────────────────────


def rebuild_chatroom_dynamic_agents() -> None:
    """Recreate dynamic Agents for every room on startup.

    Called from ``api.main.reload_agents`` after ``registry.start_all()`` so
    dynamic members keep working across restarts. Failures are logged and
    skipped — startup must not be blocked by a stale dynamic_member entry.
    """

    cap_registry = _get_capability_registry()
    agent_registry = _get_agent_registry()
    if cap_registry is None or agent_registry is None:
        logger.info(
            "skip rebuild_chatroom_dynamic_agents: registries not ready"
        )
        return

    try:
        rooms = ChatroomStore().list_rooms()
    except Exception as exc:  # pragma: no cover
        logger.warning("rebuild_chatroom_dynamic_agents: list_rooms failed: %s", exc)
        return

    rebuilt = 0
    for summary in rooms:
        room_id = summary.get("id")
        if not room_id:
            continue
        room = ChatroomStore().get_room(room_id)
        if not room:
            continue

        for spec in room.get("dynamic_members") or []:
            name = str(spec.get("name") or "").strip()
            if not name:
                continue
            base = str(spec.get("base_agent") or "generic").strip() or "generic"
            role_prompt = str(spec.get("role_prompt") or "")

            # 若名字已被普通 yaml agent 占用，跳过，避免覆盖
            if agent_registry.get(name) is not None and name != base:
                logger.warning(
                    "rebuild_chatroom_dynamic_agents: name '%s' already taken in agent registry, skip",
                    name,
                )
                continue

            agent = _build_dynamic_agent(name, role_prompt, base)
            if agent is None:
                logger.warning(
                    "rebuild_chatroom_dynamic_agents: base_agent '%s' for '%s' missing, skip",
                    base,
                    name,
                )
                continue

            agent_registry.register(agent)
            cap_registry.register_native(AgentCapability(agent, None))
            rebuilt += 1

    if rebuilt:
        logger.info("rebuild_chatroom_dynamic_agents: rebuilt %d dynamic agents", rebuilt)
