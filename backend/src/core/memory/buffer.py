"""Global conversation buffer for private assistant memory reflection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


EARLY_REFLECTION_KEYWORDS = (
    "记住",
    "记一下",
    "帮我记",
    "以后默认",
    "以后都",
    "默认用",
    "我喜欢",
    "我不喜欢",
    "项目决定",
    "毕设",
    "需求变更",
    "todo",
    "待办",
    "下次",
    "之后要",
    "remember",
    "note that",
    "keep in mind",
    "from now on",
    "default to",
    "i like",
    "i don't like",
    "i dislike",
    "my preference",
    "my project",
    "project decision",
    "requirement change",
    "requirements changed",
    "thesis",
    "next time",
    "later we should",
)

EARLY_REFLECTION_REGEXES = (
    r"我的[^，。！？\n]{1,24}是",
    r"my [a-z0-9_ -]{1,32} is\b",
)

EARLY_REFLECTION_EXCLUSION_KEYWORDS = (
    "traceback",
    "stack trace",
    "exception",
    "报错",
    "错误日志",
    "编译失败",
    "测试失败",
    "临时",
    "随便",
    "这次",
)


def should_reflect_early(user_text: str) -> bool:
    """Return True when a user message likely contains long-term memory signal.

    This deliberately uses lightweight heuristics instead of an LLM call. It
    biases toward explicit preferences, project decisions, todos, and durable
    profile facts while avoiding common one-off troubleshooting chatter.
    """

    import re

    text = str(user_text or "").strip()
    if not text:
        return False

    lowered = text.lower()
    if any(keyword in lowered for keyword in EARLY_REFLECTION_EXCLUSION_KEYWORDS):
        # Explicit memory commands still win over exclusion words.
        explicit = ("记住", "记一下", "帮我记", "remember", "note that")
        return any(keyword in lowered for keyword in explicit)

    if any(keyword in lowered for keyword in EARLY_REFLECTION_KEYWORDS):
        return True

    return any(
        re.search(pattern, lowered, flags=re.IGNORECASE)
        for pattern in EARLY_REFLECTION_REGEXES
    )


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
        self._scopes: dict[str, dict[str, Any]] = {}

    def append_exchange(
        self,
        user_text: str,
        assistant_text: str,
        *,
        source: str,
        session_id: Optional[str] = None,
        force_reflect: bool = False,
        significant: Optional[bool] = None,
    ) -> Optional[dict[str, Any]]:
        """Append one user/assistant exchange and maybe return a reflection window."""

        state = self._scope_state(source=source, session_id=session_id)
        messages = state["messages"]
        user_message = self._make_message(
            "user",
            user_text,
            source,
            session_id,
            index=state["next_index"],
        )
        state["next_index"] += 1
        assistant_message = self._make_message(
            "assistant",
            assistant_text,
            source,
            session_id,
            index=state["next_index"],
        )
        state["next_index"] += 1
        messages.extend([user_message, assistant_message])

        pending = messages[state["last_summarized_index"] :]
        early = force_reflect or (
            should_reflect_early(user_text) if significant is None else bool(significant)
        )
        threshold_met = len(pending) >= self.min_turns * 2
        if not threshold_met and not early:
            return None

        window = pending[-self.max_window_messages :]
        state["last_summarized_index"] = len(messages)
        trigger_reason = "threshold" if threshold_met else "significant"
        if force_reflect:
            trigger_reason = "forced"
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
                "trigger_reason": trigger_reason,
                **({"session_id": session_id} if session_id else {}),
            },
        }

    def _make_message(
        self,
        role: str,
        content: str,
        source: str,
        session_id: Optional[str],
        *,
        index: int,
    ) -> dict[str, Any]:
        message = {
            "index": index,
            "role": role,
            "content": str(content),
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
        }
        if session_id:
            message["session_id"] = session_id
        return message

    def _scope_state(self, *, source: str, session_id: Optional[str]) -> dict[str, Any]:
        key = f"session:{session_id}" if session_id else f"source:{source}"
        if key not in self._scopes:
            self._scopes[key] = {
                "messages": [],
                "last_summarized_index": 0,
                "next_index": 0,
            }
        return self._scopes[key]
