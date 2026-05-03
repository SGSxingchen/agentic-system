# Private Assistant Memory Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight global private-assistant memory layer with structured memory metadata, explainable retrieval, automatic chat reflection, and prompt injection.

**Architecture:** Reuse the existing memory store and API surface. Add focused memory helpers under `backend/src/core/memory/`, enhance `MemoryFormation` and `MemoryRetriever`, then connect the generic configured `Agent` plus REST/WebSocket chat entrypoints to retrieval and post-response reflection. Keep all memory global by default; session ids are source metadata only.

**Tech Stack:** Python 3.10+, FastAPI, pytest/pytest-asyncio, React/TypeScript/Vite.

---

## File Structure

- Create `backend/src/core/memory/processor.py`: parse LLM reflection JSON into validated structured memory candidates.
- Create `backend/src/core/memory/buffer.py`: collect global chat turns and expose reflection windows.
- Modify `backend/src/core/memory/formation.py`: add structured memory creation, quality filtering, approximate deduplication, and safer forgetting.
- Modify `backend/src/core/memory/retriever.py`: add metadata-aware scoring, deduplication, and non-persistent retrieval explanations.
- Modify `backend/src/core/memory/__init__.py`: export new public helpers.
- Modify `backend/src/core/agent/agent.py`: support injected memory context in the system prompt.
- Modify `backend/src/api/dependencies.py`: store the global conversation memory buffer.
- Modify `backend/src/api/main.py`: initialize the buffer and wire REST chat reflection.
- Modify `backend/src/api/websocket/handlers.py`: wire WebSocket chat reflection and preserve response behavior.
- Modify `backend/src/api/routes/memory.py`: return retrieval explanations from search.
- Modify `backend/src/capabilities/tools/memory_search.py`: expose assistant-friendly context and score breakdown.
- Modify `frontend/src/components/MemoryPanel.tsx`: render memory kind, topics, quality, and retrieval score details.
- Add tests in `backend/tests/unit/test_memory_living.py`, `backend/tests/unit/test_agent_system.py`, `backend/tests/unit/test_websocket_deps_schemas.py`, and `backend/tests/integration/test_api.py`.

---

### Task 1: Memory Processor

**Files:**
- Create: `backend/src/core/memory/processor.py`
- Modify: `backend/src/core/memory/__init__.py`
- Test: `backend/tests/unit/test_memory_living.py`

- [ ] **Step 1: Write failing tests for JSON parsing and validation**

Add tests that import `MemoryProcessor` and verify:

```python
async def test_processor_parses_markdown_json_candidates():
    processor = MemoryProcessor(llm_client=FakeReflectionLLM("""```json
    {"memories": [{"memory_type": "semantic", "memory_kind": "preference", "canonical_summary": "用户偏好简洁回答。", "assistant_context": "用户喜欢简洁回答。", "topics": ["沟通"], "key_facts": ["偏好简洁"], "importance": 0.8, "confidence": 0.9, "summary_quality": 0.9}]}
    ```"""))
    result = await processor.process_conversation([
        {"role": "user", "content": "我喜欢你回答简洁一点", "timestamp": "2026-04-26T00:00:00"}
    ], source_window={"start_index": 0, "end_index": 0})
    assert len(result) == 1
    assert result[0]["metadata"]["memory_kind"] == "preference"
    assert result[0]["metadata"]["assistant_context"] == "用户喜欢简洁回答。"
```

```python
async def test_processor_rejects_low_quality_candidates():
    processor = MemoryProcessor(llm_client=FakeReflectionLLM('{"memories": [{"canonical_summary": "x", "summary_quality": 0.1, "confidence": 0.1}]}'))
    result = await processor.process_conversation([{"role": "user", "content": "x"}], source_window={})
    assert result == []
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py -q`

Expected: import failure for `core.memory.processor` or missing `MemoryProcessor`.

- [ ] **Step 3: Implement `MemoryProcessor` minimally**

Implement:

```python
class MemoryProcessor:
    async def process_conversation(self, turns, source_window=None) -> list[dict]:
        response = await self.llm.chat([...])
        parsed = self._parse_json(response.content or "")
        return [self._candidate_to_memory(item, source_window) for item in parsed["memories"] if self._is_valid(item)]
```

It must strip markdown fences, extract JSON object slices, clamp numeric fields to `0..1`, default `memory_type` to `semantic`, default `memory_kind` to `other`, and put structured fields under `metadata`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py -q`

Expected: processor tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/core/memory/processor.py backend/src/core/memory/__init__.py backend/tests/unit/test_memory_living.py
git commit -m "feat: add private memory processor"
```

---

### Task 2: Structured Formation And Deduplication

**Files:**
- Modify: `backend/src/core/memory/formation.py`
- Test: `backend/tests/unit/test_memory_living.py`

- [ ] **Step 1: Write failing tests for structured creation and deduplication**

Add tests:

```python
async def test_formation_creates_structured_private_memory(store):
    formation = MemoryFormation(store)
    memory = await formation.create_structured_memory({
        "content": "用户偏好简洁回答。",
        "memory_type": "semantic",
        "importance": 0.8,
        "metadata": {"memory_kind": "preference", "canonical_summary": "用户偏好简洁回答。", "assistant_context": "回答要简洁。", "summary_quality": 0.9}
    })
    assert memory.content == "用户偏好简洁回答。"
    assert memory.metadata["schema_version"] == "private_memory_v1"
```

```python
async def test_formation_deduplicates_similar_private_memories(store):
    formation = MemoryFormation(store)
    first = await formation.create_structured_memory({...})
    second = await formation.create_structured_memory({...same memory_kind and near-identical summary...})
    assert first.id == second.id
    assert await store.count() == 1
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py -q`

Expected: `MemoryFormation` has no `create_structured_memory`.

- [ ] **Step 3: Implement structured formation**

Add `create_structured_memory(candidate)` that validates `summary_quality >= 0.35` and `confidence >= 0.35`, stores `content = canonical_summary or content`, merges default metadata, searches existing memories, and merges exact or high-Jaccard duplicates.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py backend/tests/unit/test_memory.py -q`

Expected: all memory formation tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/core/memory/formation.py backend/tests/unit/test_memory_living.py
git commit -m "feat: add structured memory formation"
```

---

### Task 3: Explainable Retrieval

**Files:**
- Modify: `backend/src/core/memory/retriever.py`
- Modify: `backend/src/api/routes/memory.py`
- Modify: `backend/src/capabilities/tools/memory_search.py`
- Test: `backend/tests/unit/test_memory_living.py`
- Test: `backend/tests/integration/test_api.py`

- [ ] **Step 1: Write failing tests for retrieval explanations**

Add tests:

```python
async def test_retrieve_with_scores_uses_metadata_and_last_accessed(store):
    retriever = MemoryRetriever(store)
    old = Memory(content="用户喜欢简洁回答", metadata={"canonical_summary": "用户喜欢简洁回答", "topics": ["沟通"]}, importance=0.9, last_accessed=datetime.now() - timedelta(days=20))
    recent = Memory(content="用户喜欢简洁回答", metadata={"assistant_context": "回答要简洁"}, importance=0.6, last_accessed=datetime.now())
    await store.save(old)
    await store.save(recent)
    results = await retriever.retrieve_with_scores("请简洁回答", max_results=1)
    assert results[0]["memory"].id == recent.id
    assert "breakdown" in results[0]["retrieval"]
```

```python
async def test_memory_search_api_returns_retrieval_breakdown(client):
    ...
    assert "retrieval" in body["data"][0]
    assert "score" in body["data"][0]["retrieval"]
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py backend/tests/integration/test_api.py::TestMemoryAPI::test_search_memory -q`

Expected: `retrieve_with_scores` missing or API response lacks `retrieval`.

- [ ] **Step 3: Implement explainable retrieval**

Add `retrieve_with_scores()` returning `{"memory": Memory, "retrieval": {...}}`. Keep `retrieve()` backward-compatible by returning only memories. Score with rank relevance, metadata text overlap, importance, recency from `max(created_at, last_accessed)`, frequency, and Jaccard deduplication.

- [ ] **Step 4: Update API and tool responses**

`/api/memory/search` should serialize each memory with a top-level `retrieval`. `memory_search` should return `assistant_context`, `metadata`, and `retrieval` per result.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py backend/tests/unit/test_memory.py backend/tests/integration/test_api.py -q`

Expected: memory and API tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/core/memory/retriever.py backend/src/api/routes/memory.py backend/src/capabilities/tools/memory_search.py backend/tests/unit/test_memory_living.py backend/tests/integration/test_api.py
git commit -m "feat: add explainable memory retrieval"
```

---

### Task 4: Conversation Buffer And Reflection Hooks

**Files:**
- Create: `backend/src/core/memory/buffer.py`
- Modify: `backend/src/api/dependencies.py`
- Modify: `backend/src/api/main.py`
- Modify: `backend/src/api/websocket/handlers.py`
- Modify: `backend/src/core/memory/__init__.py`
- Test: `backend/tests/unit/test_memory_living.py`
- Test: `backend/tests/unit/test_websocket_deps_schemas.py`

- [ ] **Step 1: Write failing tests for buffer and dependency wiring**

Add tests:

```python
async def test_conversation_buffer_returns_reflection_window():
    buffer = ConversationMemoryBuffer(min_turns=1)
    window = buffer.append_exchange("hello", "hi", source="rest_chat")
    assert window is not None
    assert window["source_window"]["message_count"] == 2
```

```python
def test_set_get_memory_buffer():
    sentinel = object()
    set_memory_buffer(sentinel)
    assert get_memory_buffer() is sentinel
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py backend/tests/unit/test_websocket_deps_schemas.py -q`

Expected: missing `ConversationMemoryBuffer` and dependency getters/setters.

- [ ] **Step 3: Implement buffer and dependency state**

Add `ConversationMemoryBuffer` with `append_exchange(user_text, assistant_text, source, session_id=None)` and a private monotonically increasing message index. Add `set_memory_buffer()` and `get_memory_buffer()`.

- [ ] **Step 4: Wire non-blocking reflection**

In REST and WebSocket chat, after sending the assistant response, append the exchange. If a window is returned, call `MemoryProcessor.process_conversation()`, then `MemoryFormation.create_structured_memory()` for each candidate. Catch and log all reflection errors.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `python3 -m pytest backend/tests/unit/test_memory_living.py backend/tests/unit/test_websocket_deps_schemas.py -q`

Expected: buffer and dependency tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/core/memory/buffer.py backend/src/core/memory/__init__.py backend/src/api/dependencies.py backend/src/api/main.py backend/src/api/websocket/handlers.py backend/tests/unit/test_memory_living.py backend/tests/unit/test_websocket_deps_schemas.py
git commit -m "feat: add chat memory reflection"
```

---

### Task 5: Assistant Prompt Injection

**Files:**
- Modify: `backend/src/core/agent/agent.py`
- Modify: `backend/src/api/main.py`
- Modify: `backend/src/api/websocket/handlers.py`
- Test: `backend/tests/unit/test_agent_system.py`

- [ ] **Step 1: Write failing tests for memory context injection**

Add test:

```python
async def test_run_injects_memory_context_into_system_prompt():
    llm = RecordingLLMClient(LLMResponse(content="ok", stop_reason="end_turn"))
    agent = Agent(name="assistant", llm_client=llm, system_prompt="base")
    await agent.run({"message": "hello", "memory_context": "- 用户喜欢简洁回答。"})
    assert llm.calls[0][0]["content"] == "base\n\n[长期记忆]\n- 用户喜欢简洁回答。"
```

- [ ] **Step 2: Run test to verify RED**

Run: `python3 -m pytest backend/tests/unit/test_agent_system.py::TestAgentRun::test_run_injects_memory_context_into_system_prompt -q`

Expected: system prompt does not include memory context.

- [ ] **Step 3: Implement Agent injection**

Update `_build_messages()` to append sanitized `memory_context` to the system prompt and exclude `memory_context` from `_build_user_message()`.

- [ ] **Step 4: Wire retrieval in chat entrypoints**

Before executing assistant, call memory retriever with the user message, format up to three items using `assistant_context` / `canonical_summary` / `content`, pass as `memory_context`, and include `memories_used` in responses.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `python3 -m pytest backend/tests/unit/test_agent_system.py backend/tests/unit/test_memory_living.py -q`

Expected: Agent and memory tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/core/agent/agent.py backend/src/api/main.py backend/src/api/websocket/handlers.py backend/tests/unit/test_agent_system.py
git commit -m "feat: inject private memories into assistant"
```

---

### Task 6: Frontend Metadata Display And Final Verification

**Files:**
- Modify: `frontend/src/components/MemoryPanel.tsx`
- Test: build and full backend tests

- [ ] **Step 1: Update MemoryPanel rendering**

Render `metadata.memory_kind`, `metadata.topics`, `metadata.summary_quality`, and optional `retrieval.score` / `retrieval.breakdown`.

- [ ] **Step 2: Build frontend**

Run: `npm run build` in `frontend/`

Expected: TypeScript and Vite build pass.

- [ ] **Step 3: Run full backend tests**

Run: `python3 -m pytest backend/tests -q`

Expected: all backend tests pass.

- [ ] **Step 4: Commit final UI and docs touchups**

```bash
git add frontend/src/components/MemoryPanel.tsx
git commit -m "feat: show private memory metadata"
```

---

## Self-Review

Spec coverage:

- Automatic conversation memory formation: Task 1 and Task 4.
- Global private memory pool with no session filtering: Task 1 metadata and Task 3 retrieval tests.
- Structured metadata and dual summaries: Task 1 and Task 2.
- Explainable retrieval and deduplication: Task 3.
- Assistant prompt injection: Task 5.
- Frontend visibility: Task 6.
- Error isolation for reflection: Task 4.

No placeholders remain. Function names introduced in later tasks are defined before use: `MemoryProcessor`, `ConversationMemoryBuffer`, `create_structured_memory`, `retrieve_with_scores`, `set_memory_buffer`, and `get_memory_buffer`.
