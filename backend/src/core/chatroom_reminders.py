"""Chatroom runtime reminder builder — Spec 2 §8.

Generates short, "live" reminders for the speaking Agent based on changes that
happened *after* the speaker's last message: goal updates, new members joining,
@-mentions in the triggering message, etc. Truncated to 3 lines so it never
buries the actual conversation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


_MAX_REMINDERS = 3


def _last_speech_at(messages: List[Dict[str, Any]], target_agent: str) -> Optional[str]:
    """Return the ``created_at`` of the speaker's most recent message; ``None``
    when they have not spoken in this room yet."""

    sender = f"agent:{target_agent}"
    last: Optional[str] = None
    for msg in messages:
        if msg.get("sender") == sender:
            ts = msg.get("created_at")
            if ts and (last is None or str(ts) > str(last)):
                last = str(ts)
    return last


def _goal_change_lines(
    room: Dict[str, Any],
    last_speech_at: Optional[str],
) -> List[str]:
    history = room.get("goal_history") or []
    if not history:
        return []
    new_changes = []
    for entry in history:
        ts = str(entry.get("set_at") or "")
        if not ts:
            continue
        if last_speech_at is None or ts > last_speech_at:
            new_changes.append(entry)
    if not new_changes:
        return []
    new_goal = (room.get("goal") or "").strip() or "（未设定）"
    by = str(new_changes[-1].get("set_by") or "某成员")
    return [f'目标在你上次发言后被 {by} 改过 {len(new_changes)} 次，现在是："{new_goal}"']


def _new_member_lines(
    room: Dict[str, Any],
    last_speech_at: Optional[str],
) -> List[str]:
    dynamic = room.get("dynamic_members") or []
    new_members: List[str] = []
    for entry in dynamic:
        name = str(entry.get("name") or "")
        joined_at = str(entry.get("joined_at") or "")
        if not name or not joined_at:
            continue
        if last_speech_at is None or joined_at > last_speech_at:
            new_members.append(name)
    if not new_members:
        return []
    return [f"新成员加入：{', '.join(new_members)}"]


def _mention_lines(
    room: Dict[str, Any],
    target_agent: str,
    parent_message_id: Optional[str],
) -> List[str]:
    if not parent_message_id:
        return []
    messages = room.get("messages") or []
    parent = next(
        (m for m in messages if m.get("id") == parent_message_id),
        None,
    )
    if parent is None:
        return []
    mentions = parent.get("mentions") or []
    if target_agent not in mentions:
        return []
    sender = str(parent.get("sender") or "")
    label = sender.split(":", 1)[1] if sender.startswith("agent:") else sender or "user"
    return [f'你刚被 @ 了 — 来自 {label} 的消息 (id={parent_message_id})']


def build_system_reminders(
    room: Dict[str, Any],
    target_agent: str,
    parent_message_id: Optional[str] = None,
) -> str:
    """Build a short reminder block (or empty string) for the next speech turn.

    Signals are collected in priority order: at-mention → goal change → new
    member. The output is truncated to ``_MAX_REMINDERS`` (3) lines so attention
    is not diluted.
    """

    messages = room.get("messages") or []
    last_at = _last_speech_at(messages, target_agent)

    lines: List[str] = []
    # Mention 优先（最即时的"找你"信号）
    lines.extend(_mention_lines(room, target_agent, parent_message_id))
    # 然后是 goal 变化
    lines.extend(_goal_change_lines(room, last_at))
    # 最后是新成员
    lines.extend(_new_member_lines(room, last_at))

    truncated = lines[:_MAX_REMINDERS]
    return "\n".join(truncated)


__all__ = ["build_system_reminders"]
