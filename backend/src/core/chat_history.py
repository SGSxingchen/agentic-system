"""Persistent chat session storage.

The chat UI treats each session as a separate page. This store keeps those
pages in a small JSON file so history survives browser refreshes and restarts.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORE_PATH = PROJECT_ROOT / "data" / "chat_sessions.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_title(content: str) -> str:
    title = " ".join(content.strip().split())
    if not title:
        return "新的聊天"
    return title[:28] + ("..." if len(title) > 28 else "")


class ChatHistoryStore:
    """File-backed store for multi-session chat history."""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        configured_path = path or os.getenv("CHAT_SESSIONS_FILE") or DEFAULT_STORE_PATH
        self.path = Path(configured_path)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return session summaries sorted by latest update."""

        data = self._read()
        summaries = [self._to_summary(session) for session in data["sessions"]]
        summaries.sort(key=lambda item: item["updated_at"], reverse=True)
        return summaries

    def create_session(self, title: Optional[str] = None) -> Dict[str, Any]:
        """Create an empty session page."""

        now = _utc_now()
        session = {
            "id": uuid.uuid4().hex,
            "title": title.strip() if title and title.strip() else "新的聊天",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

        data = self._read()
        data["sessions"].append(session)
        self._write(data)
        return deepcopy(session)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        session = self._find_session(data, session_id)
        return deepcopy(session) if session else None

    def update_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        data = self._read()
        session = self._find_session(data, session_id)
        if not session:
            return None

        if title is not None:
            cleaned = title.strip()
            if cleaned:
                session["title"] = cleaned
        session["updated_at"] = _utc_now()

        self._write(data)
        return deepcopy(session)

    def delete_session(self, session_id: str) -> bool:
        data = self._read()
        before = len(data["sessions"])
        data["sessions"] = [
            session for session in data["sessions"] if session.get("id") != session_id
        ]
        if len(data["sessions"]) == before:
            return False

        self._write(data)
        return True

    def add_message(
        self,
        session_id: str,
        message: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        data = self._read()
        session = self._find_session(data, session_id)
        if not session:
            return None

        normalized = {
            "id": str(message.get("id") or f"msg-{uuid.uuid4().hex}"),
            "type": str(message["type"]),
            "content": str(message["content"]),
            "timestamp": str(message.get("timestamp") or _utc_now()),
        }
        if "memoriesUsed" in message and message["memoriesUsed"] is not None:
            normalized["memoriesUsed"] = message["memoriesUsed"]
        if "elapsedMs" in message and message["elapsedMs"] is not None:
            normalized["elapsedMs"] = message["elapsedMs"]
        if isinstance(message.get("usage"), dict):
            normalized["usage"] = message["usage"]
        if isinstance(message.get("toolCalls"), list):
            normalized["toolCalls"] = [
                item for item in message["toolCalls"] if isinstance(item, dict)
            ]

        session["messages"].append(normalized)
        session["updated_at"] = _utc_now()

        if (
            session.get("title") == "新的聊天"
            and normalized["type"] == "user"
            and len(session["messages"]) == 1
        ):
            session["title"] = _derive_title(normalized["content"])

        self._write(data)
        return deepcopy(session)

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"sessions": []}

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {"sessions": []}

        if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
            return {"sessions": []}

        sessions = [
            self._normalize_session(item)
            for item in data["sessions"]
            if isinstance(item, dict) and item.get("id")
        ]
        return {"sessions": sessions}

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            temp_name = file.name

        os.replace(temp_name, self.path)

    def _find_session(
        self,
        data: Dict[str, Any],
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        return next(
            (
                session
                for session in data["sessions"]
                if str(session.get("id")) == session_id
            ),
            None,
        )

    def _normalize_session(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        now = _utc_now()
        messages = raw.get("messages")
        if not isinstance(messages, list):
            messages = []

        return {
            "id": str(raw["id"]),
            "title": str(raw.get("title") or "新的聊天"),
            "created_at": str(raw.get("created_at") or now),
            "updated_at": str(raw.get("updated_at") or raw.get("created_at") or now),
            "messages": [
                message for message in messages if isinstance(message, dict)
            ],
        }

    def _to_summary(self, session: Dict[str, Any]) -> Dict[str, Any]:
        messages = session.get("messages") or []
        last_message = messages[-1]["content"] if messages else ""
        return {
            "id": session["id"],
            "title": session.get("title") or "新的聊天",
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "message_count": len(messages),
            "last_message": last_message,
        }
