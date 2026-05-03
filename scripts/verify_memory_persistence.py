#!/usr/bin/env python3
"""Verify the automatic persistent memory loop without a live server.

It proves the minimum闭环:
1. one completed chat exchange is reflected into a structured memory;
2. stats increase and search recalls it;
3. a new ChromaStore instance pointed at the same persist_dir can still read it.

Usage:
  python scripts/verify_memory_persistence.py [persist_dir]
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from core.llm.base import BaseLLMClient, LLMResponse  # noqa: E402
from core.memory import (  # noqa: E402
    ChromaStore,
    ConversationMemoryBuffer,
    MemoryFormation,
    MemoryRetriever,
)
from core.memory.processor import MemoryProcessor  # noqa: E402


class FakeReflectionLLM(BaseLLMClient):
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> LLMResponse:
        return LLMResponse(
            content='''{
  "memories": [
    {
      "memory_type": "semantic",
      "memory_kind": "preference",
      "canonical_summary": "用户偏好简洁回答。",
      "assistant_context": "用户喜欢助手回答简洁。",
      "topics": ["沟通"],
      "key_facts": ["偏好简洁"],
      "importance": 0.8,
      "confidence": 0.9,
      "summary_quality": 0.9
    }
  ]
}''',
            stop_reason="end_turn",
        )


async def main() -> int:
    persist_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "chroma_verify"
    if persist_dir.exists():
        shutil.rmtree(persist_dir)

    collection_name = "agent_memories_verify"
    store = ChromaStore(collection_name=collection_name, persist_dir=str(persist_dir))
    formation = MemoryFormation(store)
    buffer = ConversationMemoryBuffer(min_turns=1)
    processor = MemoryProcessor(FakeReflectionLLM())

    window = buffer.append_exchange(
        "我喜欢你回答简洁一点",
        "好的，我会保持简洁。",
        source="verify_script",
        session_id="verify-session",
    )
    assert window is not None
    candidates = await processor.process_conversation(
        window["turns"],
        source_window=window["source_window"],
    )
    for candidate in candidates:
        await formation.create_structured_memory(candidate)

    stats = await formation.get_stats()
    assert stats["total"] >= 1, stats

    recalled = await MemoryRetriever(store).retrieve_with_scores("请简洁回答", max_results=3)
    assert recalled, "memory search did not recall the new memory"

    reloaded = ChromaStore(collection_name=collection_name, persist_dir=str(persist_dir))
    reloaded_stats = await MemoryFormation(reloaded).get_stats()
    assert reloaded_stats["total"] >= 1, reloaded_stats

    print("OK memory persistence verified")
    print({
        "persist_dir": str(persist_dir),
        "stats": stats,
        "reloaded_stats": reloaded_stats,
        "first_recall": recalled[0]["memory"].to_dict(),
        "retrieval": recalled[0]["retrieval"],
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except ImportError as exc:
        print(f"ERROR: chromadb is required for this verification: {exc}", file=sys.stderr)
        print("Install with: pip install chromadb", file=sys.stderr)
        raise SystemExit(2)
