"""Global conversation buffer for private assistant memory reflection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


class ConversationMemoryBuffer:
    """Collect chat exchanges and return reflection windows after a threshold."""

    def __init__(
        self,
        *,
        min_turns: int = 3,
        max_window_messages: int = 12,
    ) -> None:
        self.min_turns = max(1, min_turns)
        self.max_window_messages = max(2, max_window_messages)
        self._messages: list[dict[str, Any]] = []
        self._last_summarized_index = 0
        self._next_index = 0

    def append_exchange(
        self,
        user_text: str,
        assistant_text: str,
        *,
        source: str,
        session_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Append one user/assistant exchange and maybe return a reflection window."""

        user_message = self._make_message("user", user_text, source, session_id)
        assistant_message = self._make_message("assistant", assistant_text, source, session_id)
        self._messages.extend([user_message, assistant_message])

        pending = self._messages[self._last_summarized_index :]
        if len(pending) < self.min_turns * 2:
            return None

        window = pending[-self.max_window_messages :]
        self._last_summarized_index = len(self._messages)
        return {
            "turns": [
                {
                    "role": item["role"],
                    "content": item["content"],
                    "timestamp": item["timestamp"],
                }
                for item in window
            ],
            "source_window": {
                "start_index": window[0]["index"],
                "end_index": window[-1]["index"],
                "message_count": len(window),
                "started_at": window[0]["timestamp"],
                "ended_at": window[-1]["timestamp"],
                "source": source,
                **({"session_id": session_id} if session_id else {}),
            },
        }

    def _make_message(
        self,
        role: str,
        content: str,
        source: str,
        session_id: Optional[str],
    ) -> dict[str, Any]:
        message = {
            "index": self._next_index,
            "role": role,
            "content": str(content),
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
        }
        if session_id:
            message["session_id"] = session_id
        self._next_index += 1
        return message
