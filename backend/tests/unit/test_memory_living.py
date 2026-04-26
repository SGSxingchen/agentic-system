"""Private assistant memory behavior tests."""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.base import BaseLLMClient, LLMResponse
from core.memory.processor import MemoryProcessor


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
