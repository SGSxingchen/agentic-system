"""General text processing capability."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema


class TextProcessorCapability(CapabilityBase):
    """Small deterministic text utilities for assistant workflows."""

    _STOPWORDS = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "you",
        "are",
        "一个",
        "这个",
        "那个",
        "可以",
        "需要",
        "以及",
        "进行",
    }

    @property
    def name(self) -> str:
        return "text_processor"

    @property
    def description(self) -> str:
        return "文本处理工具：统计、清洗、关键词提取、大小写转换和 slug 生成"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "待处理文本",
                    },
                    "operation": {
                        "type": "string",
                        "description": "操作: stats | clean | keywords | uppercase | lowercase | slugify",
                        "default": "stats",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "关键词数量上限，默认 10",
                        "default": 10,
                    },
                },
                "required": ["text"],
            },
            returns="文本处理结果",
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        text = str(kwargs.get("text", ""))
        operation = str(kwargs.get("operation") or "stats")
        limit = int(kwargs.get("limit", 10) or 10)

        if operation == "clean":
            return {"text": self._clean(text)}
        if operation == "keywords":
            return {"keywords": self._keywords(text, max(1, min(limit, 50)))}
        if operation == "uppercase":
            return {"text": text.upper()}
        if operation == "lowercase":
            return {"text": text.lower()}
        if operation == "slugify":
            return {"text": self._slugify(text)}

        words = self._words(text)
        return {
            "characters": len(text),
            "characters_no_spaces": len(re.sub(r"\s+", "", text)),
            "words": len(words),
            "lines": len(text.splitlines()) if text else 0,
            "sentences": len([s for s in re.split(r"[.!?。！？]+", text) if s.strip()]),
        }

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _keywords(cls, text: str, limit: int) -> list[dict[str, Any]]:
        words = [
            word.lower()
            for word in cls._words(text)
            if len(word) >= 2 and word.lower() not in cls._STOPWORDS
        ]
        return [
            {"term": term, "count": count}
            for term, count in Counter(words).most_common(limit)
        ]

    @staticmethod
    def _words(text: str) -> list[str]:
        return re.findall(r"[\w\u4e00-\u9fff]+", text, flags=re.UNICODE)

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.strip().lower()
        text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text, flags=re.UNICODE)
        return re.sub(r"-+", "-", text).strip("-")
