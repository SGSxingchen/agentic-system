"""Private assistant memory behavior tests."""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from core.llm.base import BaseLLMClient, LLMResponse
from core.memory import InMemoryStore, Memory, MemoryFormation, MemoryRetriever, MemoryType
from core.memory.buffer import ConversationMemoryBuffer
from core.memory.processor import MemoryProcessor


@pytest.fixture
def store():
    return InMemoryStore()


class FakeReflectionLLM(BaseLLMClient):
    """Small LLM fake that returns a configured reflection response."""

    def __init__(self, content: str):
        self.content = content
        self.calls: List[List[Dict[str, Any]]] = []

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(content=self.content, stop_reason="end_turn")


async def test_processor_parses_markdown_json_candidates():
    processor = MemoryProcessor(
        llm_client=FakeReflectionLLM(
            """```json
{
  "memories": [
    {
      "memory_type": "semantic",
      "memory_kind": "preference",
      "canonical_summary": "用户偏好简洁回答。",
      "assistant_context": "用户喜欢简洁回答。",
      "topics": ["沟通"],
      "key_facts": ["偏好简洁"],
      "importance": 0.8,
      "confidence": 0.9,
      "summary_quality": 0.9
    }
  ]
}
```"""
        )
    )

    result = await processor.process_conversation(
        [
            {
                "role": "user",
                "content": "我喜欢你回答简洁一点",
                "timestamp": "2026-04-26T00:00:00",
            }
        ],
        source_window={"start_index": 0, "end_index": 0},
    )

    assert len(result) == 1
    candidate = result[0]
    assert candidate["content"] == "用户偏好简洁回答。"
    assert candidate["memory_type"] == "semantic"
    assert candidate["importance"] == 0.8
    assert candidate["metadata"]["memory_kind"] == "preference"
    assert candidate["metadata"]["assistant_context"] == "用户喜欢简洁回答。"
    assert candidate["metadata"]["source_window"] == {"start_index": 0, "end_index": 0}


async def test_processor_rejects_low_quality_candidates():
    processor = MemoryProcessor(
        llm_client=FakeReflectionLLM(
            """{
  "memories": [
    {
      "memory_type": "semantic",
      "memory_kind": "fact",
      "canonical_summary": "x",
      "assistant_context": "x",
      "summary_quality": 0.1,
      "confidence": 0.1
    }
  ]
}"""
        )
    )

    result = await processor.process_conversation(
        [{"role": "user", "content": "x"}],
        source_window={},
    )

    assert result == []


async def test_formation_creates_structured_private_memory(store):
    formation = MemoryFormation(store)

    memory = await formation.create_structured_memory(
        {
            "content": "用户偏好简洁回答。",
            "memory_type": "semantic",
            "importance": 0.8,
            "metadata": {
                "memory_kind": "preference",
                "canonical_summary": "用户偏好简洁回答。",
                "assistant_context": "回答要简洁。",
                "summary_quality": 0.9,
                "confidence": 0.9,
            },
        }
    )

    assert memory.type == MemoryType.SEMANTIC
    assert memory.content == "用户偏好简洁回答。"
    assert memory.importance == 0.8
    assert memory.metadata["schema_version"] == "private_memory_v1"
    assert memory.metadata["source"] == "chat_reflection"
    assert memory.metadata["assistant_context"] == "回答要简洁。"


async def test_formation_deduplicates_similar_private_memories(store):
    formation = MemoryFormation(store)
    candidate = {
        "content": "用户偏好简洁回答。",
        "memory_type": "semantic",
        "importance": 0.6,
        "metadata": {
            "memory_kind": "preference",
            "canonical_summary": "用户偏好简洁回答。",
            "assistant_context": "回答要简洁。",
            "topics": ["沟通"],
            "key_facts": ["偏好简洁"],
            "summary_quality": 0.9,
            "confidence": 0.9,
        },
    }

    first = await formation.create_structured_memory(candidate)
    second = await formation.create_structured_memory(
        {
            **candidate,
            "importance": 0.7,
            "metadata": {
                **candidate["metadata"],
                "topics": ["沟通", "回答风格"],
                "key_facts": ["偏好简洁", "不喜欢冗长"],
            },
        }
    )

    assert first.id == second.id
    assert await store.count() == 1
    merged = await store.get(first.id)
    assert merged is not None
    assert merged.importance > 0.6
    assert merged.metadata["topics"] == ["沟通", "回答风格"]
    assert merged.metadata["key_facts"] == ["偏好简洁", "不喜欢冗长"]


async def test_retrieve_with_scores_uses_metadata_and_last_accessed(store):
    retriever = MemoryRetriever(store)
    old_memory = Memory(
        content="用户喜欢简洁回答",
        metadata={
            "memory_kind": "preference",
            "canonical_summary": "用户喜欢简洁回答",
            "assistant_context": "回答要简洁",
            "topics": ["沟通"],
        },
        importance=0.9,
        created_at=datetime.now() - timedelta(days=30),
        last_accessed=datetime.now() - timedelta(days=20),
    )
    recent_memory = Memory(
        content="用户喜欢简洁回答",
        metadata={
            "memory_kind": "preference",
            "canonical_summary": "用户喜欢简洁回答",
            "assistant_context": "回答要非常简洁",
            "topics": ["沟通"],
        },
        importance=0.6,
        created_at=datetime.now() - timedelta(days=30),
        last_accessed=datetime.now(),
    )
    await store.save(old_memory)
    await store.save(recent_memory)

    results = await retriever.retrieve_with_scores("请简洁回答", max_results=1)

    assert len(results) == 1
    assert results[0]["memory"].id == recent_memory.id
    retrieval = results[0]["retrieval"]
    assert retrieval["score"] > 0
    assert set(retrieval["breakdown"]) == {
        "relevance",
        "importance",
        "recency",
        "frequency",
    }
    assert retrieval["deduped_similar_ids"] == [old_memory.id]


async def test_retrieve_with_scores_does_not_filter_by_source_session(store):
    retriever = MemoryRetriever(store)
    await store.save(
        Memory(
            content="用户正在准备本科毕设",
            metadata={
                "memory_kind": "project_context",
                "canonical_summary": "用户正在准备本科毕设",
                "source_window": {"session_id": "other-session"},
            },
            importance=0.8,
        )
    )

    results = await retriever.retrieve_with_scores("毕设", max_results=3)

    assert len(results) == 1
    assert results[0]["memory"].metadata["source_window"]["session_id"] == "other-session"


async def test_conversation_buffer_returns_reflection_window():
    buffer = ConversationMemoryBuffer(min_turns=1)

    window = buffer.append_exchange(
        "我喜欢简洁回答",
        "好的，我会保持简洁。",
        source="rest_chat",
        session_id="chat-1",
    )

    assert window is not None
    assert len(window["turns"]) == 2
    assert window["source_window"]["message_count"] == 2
    assert window["source_window"]["session_id"] == "chat-1"
    assert window["source_window"]["source"] == "rest_chat"


async def test_conversation_buffer_waits_until_threshold():
    buffer = ConversationMemoryBuffer(min_turns=2)

    first = buffer.append_exchange("第一轮", "回复一", source="rest_chat")
    second = buffer.append_exchange("第二轮", "回复二", source="rest_chat")

    assert first is None
    assert second is not None
    assert second["source_window"]["message_count"] == 4
