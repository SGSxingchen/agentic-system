"""Conversation reflection processor for private assistant memories."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..llm.base import BaseLLMClient
from ..prompts import build_memory_reflection_messages


PRIVATE_MEMORY_SCHEMA_VERSION = "private_memory_v1"
VALID_MEMORY_TYPES = {"episodic", "semantic", "procedural"}
VALID_MEMORY_KINDS = {
    "preference",
    "fact",
    "project_context",
    "decision",
    "todo",
    "experience",
    "other",
}


class MemoryProcessor:
    """Turn conversation windows into structured private-memory candidates."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        *,
        min_quality: float = 0.35,
        min_confidence: float = 0.35,
        max_candidates: int = 5,
    ) -> None:
        self.llm = llm_client
        self.min_quality = min_quality
        self.min_confidence = min_confidence
        self.max_candidates = max_candidates

    async def process_conversation(
        self,
        turns: list[dict[str, Any]],
        *,
        source_window: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Reflect on a conversation window and return validated memory candidates."""

        if not turns:
            return []

        response = await self.llm.chat(self._build_messages(turns))
        payload = self._parse_json(response.content or "")
        raw_memories = payload.get("memories") if isinstance(payload, dict) else None
        if not isinstance(raw_memories, list):
            return []

        candidates: list[dict[str, Any]] = []
        for raw in raw_memories[: self.max_candidates]:
            candidate = self._candidate_to_memory(raw, source_window or {})
            if candidate:
                candidates.append(candidate)
        return candidates

    def _build_messages(self, turns: list[dict[str, Any]]) -> list[dict[str, str]]:
        return build_memory_reflection_messages(turns)

    def _candidate_to_memory(
        self,
        raw: Any,
        source_window: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not isinstance(raw, dict):
            return None

        quality = self._clamp_float(raw.get("summary_quality"), default=0.0)
        confidence = self._clamp_float(raw.get("confidence"), default=0.0)
        if quality < self.min_quality or confidence < self.min_confidence:
            return None

        canonical_summary = str(
            raw.get("canonical_summary") or raw.get("summary") or raw.get("content") or ""
        ).strip()
        assistant_context = str(raw.get("assistant_context") or canonical_summary).strip()
        if not canonical_summary or not assistant_context:
            return None

        memory_type = str(raw.get("memory_type") or "semantic").strip().lower()
        if memory_type not in VALID_MEMORY_TYPES:
            memory_type = "semantic"

        memory_kind = str(raw.get("memory_kind") or "other").strip().lower()
        if memory_kind not in VALID_MEMORY_KINDS:
            memory_kind = "other"

        metadata = {
            "memory_kind": memory_kind,
            "topics": self._string_list(raw.get("topics")),
            "key_facts": self._string_list(raw.get("key_facts")),
            "canonical_summary": canonical_summary,
            "assistant_context": assistant_context,
            "confidence": confidence,
            "summary_quality": quality,
            "source_window": source_window,
            "source": str(raw.get("source") or "chat_reflection"),
            "source_agent": str(raw.get("source_agent") or "assistant"),
            "schema_version": PRIVATE_MEMORY_SCHEMA_VERSION,
        }

        return {
            "content": canonical_summary,
            "memory_type": memory_type,
            "importance": self._clamp_float(raw.get("importance"), default=0.5),
            "metadata": metadata,
        }

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(cleaned[start : end + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {}
        return {}

    @staticmethod
    def _clamp_float(value: Any, *, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(0.0, min(1.0, number))

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
