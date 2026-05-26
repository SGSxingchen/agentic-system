"""Chatroom storage and helpers (multi-agent group chat).

Phase 1 scope:
- JSON persistence (one file per room) under ``data/chatrooms/``
- CRUD for rooms and messages
- Mention parser (``@AgentName``) with escape and code-block awareness
- Context builder that produces an OpenAI/Anthropic-compatible
  ``messages`` list ready to feed an LLM, prefixed with topic / goal /
  summary / current-task system blocks.

This module is intentionally independent from the existing ``ChatHistoryStore``
and ``ChatPanel`` flow (see design spec §1.2). It only depends on the standard
library so it stays cheap to import in tests.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORE_DIR = PROJECT_ROOT / "data" / "chatrooms"
INDEX_FILENAME = "_index.json"


# ─── 默认值 ────────────────────────────────────────────────


DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_host": False,
    "host_agent": "planner",
    "recent_n": 30,
    "summary_threshold_m": 20,
    "max_relay_depth": 3,
    "max_members": 20,
    "allow_agent_invite": True,
}


# ─── 工具函数 ──────────────────────────────────────────────


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


# ─── Mention parser ───────────────────────────────────────


# 允许的 Agent 名字符：英文/数字/下划线/连字符 + Unicode 字母（含中文）
_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-一-鿿㐀-䶿]+)")


def _strip_inline_code(content: str) -> str:
    """把代码块/行内反引号包围的内容替换成等长空白，避免 @ 被解析。

    最简实现：先剥 ``` 三引号块，再剥 ` 单引号片段。匹配后用同样长度的空格
    替代，保证后续 mention 偏移不变。
    """

    def _blank(match: re.Match) -> str:
        return " " * len(match.group(0))

    # 三引号代码块（贪婪匹配最近的闭合 ```）
    triple = re.sub(r"```[\s\S]*?```", _blank, content)
    # 行内 `code`（不跨行）
    inline = re.sub(r"`[^`\n]*`", _blank, triple)
    return inline


def parse_mentions(content: str, valid_names: List[str]) -> List[str]:
    r"""从消息正文里抽出 @AgentName。

    规则：
    - 支持 ``@@`` 转义为字面量 ``@``，不会触发 mention。
    - 跳过 `` `code` `` 与 ``` ```block``` ``` 内的 @。
    - 名字字符集：``[A-Za-z0-9_\-]`` + Unicode CJK 范围。
    - 仅返回出现在 ``valid_names`` 里的名字，按出现顺序去重。
    """

    if not content or not valid_names:
        return []

    # 先剥代码段
    sanitized = _strip_inline_code(content)
    # 再处理 @@ 转义：替换成两个空格（保留长度）
    sanitized = sanitized.replace("@@", "  ")

    valid_set = set(valid_names)
    seen: List[str] = []
    for match in _MENTION_RE.finditer(sanitized):
        name = match.group(1)
        if name in valid_set and name not in seen:
            seen.append(name)
    return seen


# ─── ChatroomStore ────────────────────────────────────────


class ChatroomStore:
    """File-backed store for chatrooms.

    存储布局::

        data/chatrooms/_index.json     # 列出所有房间 id + 摘要
        data/chatrooms/{room_id}.json  # 每个房间一份 JSON

    每次写入都用临时文件 + ``os.replace`` 原子替换，避免半截 JSON。
    线程安全：模块级 ``RLock`` 守住所有公开方法（dev/单进程足够）。
    """

    _LOCK = threading.RLock()

    def __init__(self, root: Optional[Path | str] = None) -> None:
        configured = root or os.getenv("CHATROOMS_DIR") or DEFAULT_STORE_DIR
        self.root = Path(configured)
        self.index_path = self.root / INDEX_FILENAME

    # ─── 公共 API ─────────────────────────────────────────

    def list_rooms(self) -> List[Dict[str, Any]]:
        """返回所有房间的摘要列表，按 updated_at 倒序。"""

        with self._LOCK:
            ids = self._read_index()
            summaries: List[Dict[str, Any]] = []
            for room_id in ids:
                room = self._read_room(room_id)
                if room is None:
                    continue
                summaries.append(self._to_summary(room))
            summaries.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
            return summaries

    def create_room(
        self,
        title: str,
        topic: str = "",
        *,
        goal: Optional[str] = None,
        members: Optional[List[str]] = None,
        dynamic_members: Optional[List[Dict[str, Any]]] = None,
        workspace_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        room_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建新房间并落盘。"""

        now = _utc_now()
        merged_settings: Dict[str, Any] = {**DEFAULT_SETTINGS}
        if settings:
            merged_settings.update(settings)

        room: Dict[str, Any] = {
            "id": room_id or _new_id(),
            "title": str(title or "新房间").strip() or "新房间",
            "topic": str(topic or ""),
            "goal": str(goal).strip() if isinstance(goal, str) and goal.strip() else None,
            "goal_history": [],
            "members": [str(m).strip() for m in (members or []) if str(m).strip()],
            "dynamic_members": [
                self._normalize_dynamic_member(item)
                for item in (dynamic_members or [])
                if isinstance(item, dict) and item.get("name")
            ],
            "workspace_id": str(workspace_id).strip() if workspace_id else None,
            "summary": None,
            "summary_until_msg_id": None,
            "settings": merged_settings,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

        with self._LOCK:
            self._write_room(room)
            ids = self._read_index()
            if room["id"] not in ids:
                ids.append(room["id"])
                self._write_index(ids)
        return deepcopy(room)

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        with self._LOCK:
            room = self._read_room(room_id)
            return deepcopy(room) if room else None

    def update_room(self, room_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """部分更新房间字段（消息列表通过专用方法）。"""

        if not fields:
            return self.get_room(room_id)

        with self._LOCK:
            room = self._read_room(room_id)
            if room is None:
                return None

            allowed = {
                "title",
                "topic",
                "goal",
                "goal_history",
                "members",
                "dynamic_members",
                "workspace_id",
                "summary",
                "summary_until_msg_id",
                "settings",
            }
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "settings" and isinstance(value, dict):
                    merged: Dict[str, Any] = {**(room.get("settings") or {})}
                    merged.update(value)
                    room["settings"] = merged
                else:
                    room[key] = value
            room["updated_at"] = _utc_now()
            self._write_room(room)
            return deepcopy(room)

    def delete_room(self, room_id: str) -> bool:
        with self._LOCK:
            room_path = self._room_path(room_id)
            existed = room_path.exists()
            if existed:
                room_path.unlink()
            ids = self._read_index()
            if room_id in ids:
                ids.remove(room_id)
                self._write_index(ids)
            return existed

    def add_message(
        self,
        room_id: str,
        message: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """追加一条消息。返回写入后的 message dict。"""

        with self._LOCK:
            room = self._read_room(room_id)
            if room is None:
                return None
            normalized = self._normalize_message(message, room_id)
            room["messages"].append(normalized)
            room["updated_at"] = normalized.get("updated_at") or _utc_now()
            self._write_room(room)
            return deepcopy(normalized)

    def update_message(
        self,
        room_id: str,
        message_id: str,
        **fields: Any,
    ) -> Optional[Dict[str, Any]]:
        """部分更新房间内某条消息。"""

        with self._LOCK:
            room = self._read_room(room_id)
            if room is None:
                return None
            allowed = {
                "content",
                "mentions",
                "parent_message_id",
                "status",
                "task_id",
                "meta",
                "sender",
            }
            target: Optional[Dict[str, Any]] = None
            for msg in room["messages"]:
                if msg.get("id") == message_id:
                    target = msg
                    break
            if target is None:
                return None
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "meta" and isinstance(value, dict):
                    merged_meta: Dict[str, Any] = {**(target.get("meta") or {})}
                    merged_meta.update(value)
                    target["meta"] = merged_meta
                else:
                    target[key] = value
            target["updated_at"] = _utc_now()
            room["updated_at"] = target["updated_at"]
            self._write_room(room)
            return deepcopy(target)

    def list_messages(
        self,
        room_id: str,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """返回房间内消息（按时间正序）。

        ``since`` 给定时返回该 message_id 之后（不含）的消息；如果该 id 不
        存在则视为全量返回，符合"增量拉取"语义。
        """

        with self._LOCK:
            room = self._read_room(room_id)
            if room is None:
                return []
            messages: List[Dict[str, Any]] = list(room.get("messages") or [])

        if since:
            for index, msg in enumerate(messages):
                if msg.get("id") == since:
                    return deepcopy(messages[index + 1 :])
        return deepcopy(messages)

    # ─── 内部 IO ──────────────────────────────────────────

    def _room_path(self, room_id: str) -> Path:
        return self.root / f"{room_id}.json"

    def _read_index(self) -> List[str]:
        if not self.index_path.exists():
            return []
        try:
            with self.index_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, dict):
            ids = data.get("rooms")
        else:
            ids = data
        if not isinstance(ids, list):
            return []
        return [str(item) for item in ids if isinstance(item, str)]

    def _write_index(self, ids: List[str]) -> None:
        self._atomic_write(self.index_path, {"rooms": list(ids)})

    def _read_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        path = self._room_path(room_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or not data.get("id"):
            return None
        return self._normalize_room(data)

    def _write_room(self, room: Dict[str, Any]) -> None:
        self._atomic_write(self._room_path(room["id"]), room)

    def _atomic_write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            temp_name = file.name
        os.replace(temp_name, path)

    # ─── 数据归一化 ───────────────────────────────────────

    def _normalize_room(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        now = _utc_now()
        settings: Dict[str, Any] = {**DEFAULT_SETTINGS}
        if isinstance(raw.get("settings"), dict):
            settings.update(raw["settings"])

        messages = raw.get("messages")
        if not isinstance(messages, list):
            messages = []

        members_raw = raw.get("members")
        members = (
            [str(m).strip() for m in members_raw if str(m).strip()]
            if isinstance(members_raw, list)
            else []
        )

        dynamic_raw = raw.get("dynamic_members")
        dynamic_members = (
            [
                self._normalize_dynamic_member(item)
                for item in dynamic_raw
                if isinstance(item, dict) and item.get("name")
            ]
            if isinstance(dynamic_raw, list)
            else []
        )

        goal_history = raw.get("goal_history")
        if not isinstance(goal_history, list):
            goal_history = []

        return {
            "id": str(raw["id"]),
            "title": str(raw.get("title") or "新房间"),
            "topic": str(raw.get("topic") or ""),
            "goal": (
                str(raw["goal"]).strip()
                if isinstance(raw.get("goal"), str) and raw["goal"].strip()
                else None
            ),
            "goal_history": list(goal_history),
            "members": members,
            "dynamic_members": dynamic_members,
            "workspace_id": (
                str(raw["workspace_id"]).strip()
                if isinstance(raw.get("workspace_id"), str)
                and raw["workspace_id"].strip()
                else None
            ),
            "summary": (
                str(raw["summary"])
                if isinstance(raw.get("summary"), str) and raw["summary"]
                else None
            ),
            "summary_until_msg_id": (
                str(raw["summary_until_msg_id"])
                if isinstance(raw.get("summary_until_msg_id"), str)
                and raw["summary_until_msg_id"]
                else None
            ),
            "settings": settings,
            "created_at": str(raw.get("created_at") or now),
            "updated_at": str(
                raw.get("updated_at") or raw.get("created_at") or now
            ),
            "messages": [
                self._normalize_message(msg, str(raw["id"]))
                for msg in messages
                if isinstance(msg, dict)
            ],
        }

    @staticmethod
    def _normalize_dynamic_member(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": str(item.get("name") or "").strip(),
            "role_prompt": str(item.get("role_prompt") or ""),
            "base_agent": str(item.get("base_agent") or "generic"),
        }

    @staticmethod
    def _normalize_message(message: Dict[str, Any], room_id: str) -> Dict[str, Any]:
        now = _utc_now()
        sender = str(message.get("sender") or "system").strip() or "system"
        status = str(message.get("status") or "done").strip() or "done"
        mentions_raw = message.get("mentions")
        mentions = (
            [str(m).strip() for m in mentions_raw if str(m).strip()]
            if isinstance(mentions_raw, list)
            else []
        )
        meta_raw = message.get("meta")
        meta = meta_raw if isinstance(meta_raw, dict) else {}

        return {
            "id": str(message.get("id") or f"msg-{_new_id()}"),
            "room_id": str(message.get("room_id") or room_id),
            "sender": sender,
            "content": str(message.get("content") or ""),
            "mentions": mentions,
            "parent_message_id": (
                str(message["parent_message_id"])
                if isinstance(message.get("parent_message_id"), str)
                and message["parent_message_id"]
                else None
            ),
            "status": status,
            "task_id": (
                str(message["task_id"])
                if isinstance(message.get("task_id"), str) and message["task_id"]
                else None
            ),
            "meta": dict(meta),
            "created_at": str(message.get("created_at") or now),
            "updated_at": str(
                message.get("updated_at") or message.get("created_at") or now
            ),
        }

    @staticmethod
    def _to_summary(room: Dict[str, Any]) -> Dict[str, Any]:
        messages = room.get("messages") or []
        last_message_at = messages[-1]["created_at"] if messages else None
        return {
            "id": room["id"],
            "title": room.get("title") or "",
            "topic": room.get("topic") or "",
            "goal": room.get("goal"),
            "members": list(room.get("members") or []),
            "dynamic_members": list(room.get("dynamic_members") or []),
            "workspace_id": room.get("workspace_id"),
            "message_count": len(messages),
            "last_message_at": last_message_at,
            "created_at": room.get("created_at"),
            "updated_at": room.get("updated_at"),
        }


# ─── 上下文构造 ────────────────────────────────────────────


def _format_history_message(
    message: Dict[str, Any],
    target_agent_name: str,
) -> Optional[Dict[str, str]]:
    """把房间内一条消息映射为 LLM messages 列表里的一项。

    - ``user`` → role=user
    - ``agent:<name>`` → role=assistant；正文加 ``[<name>]:`` 前缀，
      让被叫的 agent 区分自己/他人。
    - ``system`` → role=user，前缀 ``[system]:``（保险起见兜底为 user，
      避免某些 LLM provider 多 system 消息时合并报错）。
    - status != ``done`` 的消息直接跳过。
    """

    if message.get("status") != "done":
        return None

    sender = str(message.get("sender") or "")
    content = str(message.get("content") or "")
    if not content.strip():
        return None

    if sender == "user":
        return {"role": "user", "content": content}
    if sender.startswith("agent:"):
        name = sender.split(":", 1)[1] or "agent"
        if name == target_agent_name:
            return {"role": "assistant", "content": content}
        return {"role": "assistant", "content": f"[{name}]: {content}"}
    if sender == "system":
        return {"role": "user", "content": f"[system]: {content}"}
    # 兜底：未知 sender 当 system 处理
    return {"role": "user", "content": f"[{sender}]: {content}"}


def build_room_context(
    room: Dict[str, Any],
    target_agent_name: str,
    *,
    recent_n: Optional[int] = None,
) -> List[Dict[str, str]]:
    """拼装房间上下文为 OpenAI/Anthropic 通用 messages 列表。

    第一条 system 块按 spec §3.3 顺序：房间主题 / 当前主要目标 /
    房间背景摘要 / 当前任务说明（含其他成员名）。

    Args:
        room: ``ChatroomStore.get_room(...)`` 返回的字典。
        target_agent_name: 即将发言的 Agent 名（用于 history 前缀切换）。
        recent_n: 覆盖 ``settings.recent_n``；None 时使用房间设置。
    """

    settings = room.get("settings") or {}
    if recent_n is None:
        try:
            recent_n = int(settings.get("recent_n", 30))
        except (TypeError, ValueError):
            recent_n = 30
    if recent_n < 0:
        recent_n = 0

    members: List[str] = list(room.get("members") or [])
    dynamic_names = [
        m.get("name") for m in (room.get("dynamic_members") or []) if m.get("name")
    ]
    all_members = list(dict.fromkeys(members + dynamic_names))
    others = [name for name in all_members if name != target_agent_name]

    topic = (room.get("topic") or "").strip() or "（未设定）"
    goal = (room.get("goal") or "").strip() or "（未设定，请根据对话推断）"
    summary = (room.get("summary") or "").strip() or "（暂无摘要）"

    others_label = "、".join(others) if others else "（暂无）"

    system_blocks = [
        "[房间主题]",
        topic,
        "",
        "[当前主要目标]",
        goal,
        "",
        "[房间背景摘要]",
        summary,
        "",
        "[当前任务]",
        f"你是群聊成员 {target_agent_name}。请在该群聊中发言。",
        f"其他成员：{others_label}。",
        "你可以用 @<name> 来召唤成员接力发言。",
    ]
    system_message = {"role": "system", "content": "\n".join(system_blocks)}

    messages: List[Dict[str, str]] = list(room.get("messages") or [])
    recent = messages[-recent_n:] if recent_n else []

    history: List[Dict[str, str]] = []
    for msg in recent:
        formatted = _format_history_message(msg, target_agent_name)
        if formatted is not None:
            history.append(formatted)

    return [system_message, *history]


__all__ = [
    "DEFAULT_SETTINGS",
    "ChatroomStore",
    "build_room_context",
    "parse_mentions",
    "should_summarize",
    "summarize_room",
]


# ─── 摘要触发与生成 ────────────────────────────────────────


def _settings_int(room: Dict[str, Any], key: str, default: int) -> int:
    """Pull an integer from ``room.settings``; clamp at 0 to avoid negative slicing."""

    settings = room.get("settings") or {}
    try:
        value = int(settings.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _summary_candidate_messages(room: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the slice of messages eligible for a fresh summary.

    Eligible = "older than the most recent N messages" AND "after the last summary cursor".
    The slice keeps the original chronological order so the LLM can reason about it.
    """

    messages: List[Dict[str, Any]] = list(room.get("messages") or [])
    if not messages:
        return []

    recent_n = _settings_int(room, "recent_n", 30)
    older_count = max(0, len(messages) - recent_n)
    earliest_window = messages[:older_count]
    if not earliest_window:
        return []

    cursor = (room.get("summary_until_msg_id") or "").strip()
    if not cursor:
        return earliest_window

    # 找到 cursor 位置，仅返回它之后的消息
    cursor_idx: Optional[int] = None
    for index, msg in enumerate(earliest_window):
        if msg.get("id") == cursor:
            cursor_idx = index
            break
    if cursor_idx is None:
        # cursor 已不在窗口内（多轮摘要后可能漂出去），保守返回整窗
        return earliest_window
    return earliest_window[cursor_idx + 1 :]


def should_summarize(room: Dict[str, Any]) -> bool:
    """Decide whether the chatroom currently needs a fresh summary pass.

    True when the count of "older than recent_n" messages that are NOT yet
    covered by ``summary_until_msg_id`` is at or above ``settings.summary_threshold_m``.
    """

    candidates = _summary_candidate_messages(room)
    threshold = _settings_int(room, "summary_threshold_m", 20)
    return len(candidates) >= max(1, threshold)


def _format_summary_input(messages: List[Dict[str, Any]]) -> str:
    """Render the messages as a chronological dialog block for the LLM."""

    lines: List[str] = []
    for msg in messages:
        sender = str(msg.get("sender") or "system")
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        # 跳过未完成消息，避免摘要里掺进半截输出
        if msg.get("status") and msg.get("status") != "done":
            continue
        lines.append(f"[{sender}] {content}")
    return "\n".join(lines)


async def summarize_room(
    room: Dict[str, Any],
    llm_client: Any,
    *,
    store: Optional["ChatroomStore"] = None,
) -> Optional[Dict[str, Any]]:
    """Generate (or refresh) the room summary; persist on success.

    Returns the updated room dict on success. Failures are swallowed with a
    ``logging.warning`` — the caller (chatroom orchestrator) deliberately runs
    this in ``asyncio.create_task`` so it never blocks the active speaker.
    """

    import logging

    logger = logging.getLogger(__name__)

    if llm_client is None or not hasattr(llm_client, "chat"):
        logger.warning("summarize_room skipped: llm_client missing or invalid")
        return None

    candidates = _summary_candidate_messages(room)
    if not candidates:
        return None

    dialog = _format_summary_input(candidates)
    if not dialog.strip():
        return None

    # 延迟导入避免循环依赖
    try:
        from .prompts import CHATROOM_SUMMARY_PROMPT
    except ImportError:  # pragma: no cover — prompts 模块缺失只能跳过
        logger.warning("summarize_room: CHATROOM_SUMMARY_PROMPT not available")
        return None

    previous = (room.get("summary") or "").strip()
    user_block = (
        ("[已有摘要]\n" + previous + "\n\n") if previous else ""
    ) + "[新增对话]\n" + dialog

    messages = [
        {"role": "system", "content": CHATROOM_SUMMARY_PROMPT},
        {"role": "user", "content": user_block},
    ]

    try:
        response = await llm_client.chat(messages)
    except Exception as exc:  # noqa: BLE001 — 静默吞错
        logger.warning("summarize_room LLM call failed: %s", exc)
        return None

    summary_text = ""
    if hasattr(response, "content"):
        summary_text = str(response.content or "").strip()
    elif isinstance(response, dict):
        summary_text = str(response.get("content") or response.get("response") or "").strip()
    elif isinstance(response, str):
        summary_text = response.strip()

    if not summary_text:
        logger.warning("summarize_room: LLM returned empty content")
        return None

    last_id = candidates[-1].get("id")
    if not last_id:
        return None

    target_store = store or ChatroomStore()
    return target_store.update_room(
        room["id"],
        summary=summary_text,
        summary_until_msg_id=str(last_id),
    )
