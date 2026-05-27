# 紧急 Bug 修复实施计划 — 2026-05-28

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each task follows the strict TDD cycle: write failing test → run failing → implement → run passing → commit.

**Goal:** 落地 spec `docs/superpowers/specs/2026-05-28-urgent-bugfix-design.md` 的三项紧急 bug 修复（A1 聊天室记忆、A2 闲聊 JSON 覆盖、A6 LLM 真重试 + UI 反馈）。**A5 不实施**，等 Spec 2 的 A13 用 `chatroom_dispatch` 工具替换。

**Architecture:** 复用现成基础设施 — `build_memory_context` / `schedule_memory_reflection`（来自 `api/websocket/handlers.py`）注入聊天室；新增独立 `core/llm/retry.py` 装饰器把 OpenAI / Anthropic 客户端瞬态错误转成有限次指数退避。`AgentProgress.retry_count` 是覆盖式语义（区别于其他累加字段），前端 `RunsPanel` / `ChatroomPanel` 读它显示"重试中 N/M"。聊天室 system 0 块插入"协作模式"覆盖 prompt + payload 强制 `output_format=text` 双保险，绕开 yaml 中 planner/coder/reviewer 的 JSON 契约（不动 yaml 本体保护工作流路径）。

**Tech Stack:** Python 3.10+, FastAPI, pytest, pytest-asyncio, React 18, TypeScript, Vite.

---

## Files

### 修改
- `backend/src/core/chatroom.py` — `DEFAULT_SETTINGS` 加 `auto_memory: True`
- `backend/src/core/chatroom_orchestrator.py` — `_build_memory_query` + memory 注入 + reflection 触发 + `_CHATROOM_OVERRIDE_PROMPT` + payload 强制 text
- `backend/src/core/llm/openai_client.py` — `chat` / `chat_stream` 包 `call_with_retry`，加 `on_retry` 参数
- `backend/src/core/llm/anthropic_client.py` — 同上
- `backend/src/core/llm/base.py` — `chat` / `chat_stream` 签名加 `on_retry: Optional[Callable] = None`
- `backend/src/core/task/types.py` — `AgentProgress.retry_count: int = 0`
- `backend/src/core/task/registry.py` — `_merge_progress` 处理 `retry_count`（覆盖语义）
- `config/system.yaml` — `llm.max_retries` / `llm.retry_initial_delay`
- `backend/src/core/agent/agent.py` — `run` / `run_stream` 在调 LLM 前注入 `on_retry` 闭包
- `backend/tests/unit/test_chatroom.py` — 新增 default settings 断言
- `backend/tests/unit/test_chatroom_orchestrator.py` — A1/A2 case
- `frontend/src/types/index.ts` — `AgentProgress` 加 `retry_count?: number`
- `frontend/src/components/RunsPanel.tsx` — 卡片渲染重试中徽标
- `frontend/src/components/RunsPanel.css` — 徽标样式
- `frontend/src/components/ChatroomPanel.tsx` — 流式中断错误文案优化 + 重试中提示
- `agentic-system/CLAUDE.md` — 状态表 / 章节同步

### 新建
- `backend/src/core/llm/retry.py` — `call_with_retry` + `_is_retryable`
- `backend/tests/unit/test_llm_retry.py` — 5 个单测
- `backend/tests/integration/test_llm_client_retry.py` — 3 个集成测

---

## 风险点与预先决策（来自 Spec 1 子 Agent 反馈）

### R1：`payload["output_format"]` 不被 capability 读取（已确认）

`backend/src/core/agent/agent.py:79` 的 `output_format` 是 `__init__` 构造参数，**不**在 `run()` 时从 `input_data` 读取（`agent.py:100-180` 主循环只用 `self._output_format`）。结论：**A2 的 (a) 强制 `output_format=text` 在当前 Agent 实现里无效**。Task 5 仅作为"防御性占位"写入（capability 真实现 input override 的那天就生效），**真正起作用的是 Task 6 的 system 块覆盖**。这一点在 Task 5 commit message 必须明确写出，避免后续误读。

### R2：流式中途断开不重试（显式取舍）

`chat_stream` 已 yield 第一个事件后再断网，**不重试**。Spec §4.2(f) 已说明，理由：重试会让前端看到重复 token。代价：用户看到"流式中断"。**前端 UI 必须在错误文案明确"流式中断，请点击重试"**——否则用户以为系统卡住。Task 12 / 13 处理这块文案。

### R3：`AgentProgress.retry_count` 是覆盖式语义

`tool_count` / `total_tokens` 是累加（见 `task/registry.py:219-222`），`retry_count` 必须是**当前重试序号的覆盖式赋值**——重试成功后由 LLM 调用方在下一次 `set_progress` 显式置 0；否则前端看到"重试中 3/3"卡死。前端展示规则：**仅当 `retry_count > 0 且 status==RUNNING` 时显示徽标**。这条规则在 Task 4 / 12 实现并测试。

---

## Task 1: A1 — 聊天室房间设置默认值加 auto_memory

**Goal**: `DEFAULT_SETTINGS` 加 `auto_memory: True`；保持向后兼容。

### 1.1 写失败测试

`backend/tests/unit/test_chatroom.py` 新增 case（紧跟 line 82 之后）：

```python
def test_default_settings_includes_auto_memory():
    """A1: 房间默认开启 auto_memory，无需用户显式打开。"""
    assert "auto_memory" in DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["auto_memory"] is True


def test_create_room_inherits_auto_memory_default(tmp_path):
    """create_room 不传 settings 时，auto_memory 应来自 DEFAULT_SETTINGS。"""
    store = ChatroomStore(tmp_path)
    room = store.create_room(title="t1", topic="topic", goal="goal", members=[])
    assert room["settings"]["auto_memory"] is True
```

### 1.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_chatroom.py::test_default_settings_includes_auto_memory \
                  backend/tests/unit/test_chatroom.py::test_create_room_inherits_auto_memory_default -v
```

预期：`KeyError` / `AssertionError`，说明默认值缺失。

### 1.3 实现

`backend/src/core/chatroom.py:38-46`：

```python
DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_host": False,
    "host_agent": "planner",
    "recent_n": 30,
    "summary_threshold_m": 20,
    "max_relay_depth": 3,
    "max_members": 20,
    "allow_agent_invite": True,
    "auto_memory": True,
}
```

### 1.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_chatroom.py -v
```

全绿 + 不破坏既有 `test_default_settings_includes_auto_host` 之类。

### 1.5 Commit

```bash
git add backend/src/core/chatroom.py backend/tests/unit/test_chatroom.py
git commit -m "feat(chatroom): default auto_memory=True in DEFAULT_SETTINGS"
```

---

## Task 2: A1 — `_build_memory_query` 纯函数

**Goal**: 提取最近 3 条消息 + prompt 拼成检索 query 的纯函数。

### 2.1 写失败测试

`backend/tests/unit/test_chatroom_orchestrator.py` 顶部新增 import：

```python
from core.chatroom_orchestrator import (
    dispatch_speaking_task,
    maybe_schedule_summary,
    _build_memory_query,
    _relay_depth,
)
```

新增 case：

```python
def test_build_memory_query_takes_last_three_messages():
    room = {
        "messages": [
            {"sender": "user", "content": "old"},
            {"sender": "user", "content": "msg1"},
            {"sender": "agent:assistant", "content": "msg2"},
            {"sender": "user", "content": "msg3"},
        ],
    }
    query = _build_memory_query(room, prompt="follow up")
    # 取尾 3 条，加 prompt
    assert "msg1" in query
    assert "msg2" in query
    assert "msg3" in query
    assert "old" not in query
    assert "follow up" in query.splitlines()[-1]


def test_build_memory_query_skips_blank_messages():
    room = {"messages": [{"sender": "user", "content": "  "}, {"sender": "user", "content": "real"}]}
    query = _build_memory_query(room, prompt=None)
    assert query.count("\n") == 0  # 单行
    assert "real" in query


def test_build_memory_query_handles_empty():
    assert _build_memory_query({"messages": []}, None) == ""
    assert _build_memory_query({}, None) == ""
```

### 2.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py::test_build_memory_query_takes_last_three_messages -v
```

预期：`ImportError: cannot import name '_build_memory_query'`。

### 2.3 实现

`backend/src/core/chatroom_orchestrator.py` 在 `_truncate`（line 144）附近新增：

```python
def _build_memory_query(room: Dict[str, Any], prompt: Optional[str]) -> str:
    """拼接最近 3 条房间消息（任意 sender）+ prompt 作为记忆检索 query。

    与 ChatPanel 单 query 相比，房间多人接力时单条消息上下文太薄；取最近 3 条
    保证检索的语义粒度。done/streaming/pending 都计入——记忆系统自己不在乎完成度。
    """
    messages = room.get("messages") or []
    tail = messages[-3:]
    parts: List[str] = []
    for msg in tail:
        sender = str(msg.get("sender") or "")
        text = str(msg.get("content") or "").strip()
        if not text:
            continue
        parts.append(f"[{sender}] {text}")
    if prompt and prompt.strip():
        parts.append(prompt.strip())
    return "\n".join(parts)
```

### 2.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -v
```

### 2.5 Commit

```bash
git add backend/src/core/chatroom_orchestrator.py backend/tests/unit/test_chatroom_orchestrator.py
git commit -m "feat(chatroom): add _build_memory_query helper for memory retrieval"
```

---

## Task 3: A1 — 注入 memory_context 到 payload

**Goal**: `_run_speaking_task` 拼 payload 时调 `build_memory_context` 注入 `memory_context`。

### 3.1 写失败测试

`backend/tests/unit/test_chatroom_orchestrator.py` 新增（参考既有 `StreamingEchoCapability` 风格）：

```python
@pytest.mark.asyncio
async def test_run_speaking_task_injects_memory_context_when_auto_memory_true(
    tmp_path, monkeypatch
):
    store = ChatroomStore(tmp_path)
    cap = StreamingEchoCapability("assistant")
    cap_registry = CapabilityRegistry()
    cap_registry.register(cap)
    task_registry = TaskRegistry()

    async def fake_build(query: str):
        return ("[mem] foo bar", 1)

    monkeypatch.setattr(
        "api.websocket.handlers.build_memory_context",
        fake_build,
    )

    with patch("core.chatroom_orchestrator._get_capability_registry", return_value=cap_registry), \
         patch("core.chatroom_orchestrator._get_task_registry", return_value=task_registry):
        room = store.create_room(title="t", topic="x", goal="y", members=["assistant"])
        store.add_message(room["id"], sender="user", content="hi")
        task_id = dispatch_speaking_task(room["id"], "assistant", store=store)
        # 等后台 task 跑完
        await asyncio.sleep(0.05)
        for _ in range(10):
            if task_registry.get(task_id).status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.05)

    assert cap.calls, "capability 应被调用"
    assert cap.calls[0].get("memory_context") == "[mem] foo bar"


@pytest.mark.asyncio
async def test_run_speaking_task_skips_memory_when_auto_memory_false(tmp_path, monkeypatch):
    store = ChatroomStore(tmp_path)
    cap = StreamingEchoCapability("assistant")
    cap_registry = CapabilityRegistry()
    cap_registry.register(cap)
    task_registry = TaskRegistry()

    called: list[str] = []

    async def spy(query: str):
        called.append(query)
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", spy)

    with patch("core.chatroom_orchestrator._get_capability_registry", return_value=cap_registry), \
         patch("core.chatroom_orchestrator._get_task_registry", return_value=task_registry):
        room = store.create_room(
            title="t", topic="x", goal="y", members=["assistant"],
            settings={"auto_memory": False},
        )
        store.add_message(room["id"], sender="user", content="hi")
        task_id = dispatch_speaking_task(room["id"], "assistant", store=store)
        await asyncio.sleep(0.05)
        for _ in range(10):
            if task_registry.get(task_id).status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.05)

    assert called == [], "auto_memory=False 时不应调 build_memory_context"
    assert "memory_context" not in cap.calls[0]
```

### 3.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py::test_run_speaking_task_injects_memory_context_when_auto_memory_true -v
```

预期：断言失败（`memory_context` 不在 `cap.calls[0]` 里）。

### 3.3 实现

`backend/src/core/chatroom_orchestrator.py:579-585`，在拼 payload 之后、`_attach_workspace` 之前插入（保留 try/except 防 import 循环）：

```python
        payload: Dict[str, Any] = {
            "messages": context_messages,
            "message": prompt or "请发言",
            "task_id": task_id,
        }

        # ── A1: 注入长期记忆（房间级 auto_memory，默认开） ──
        auto_memory = bool((room_snapshot.get("settings") or {}).get("auto_memory", True))
        if auto_memory:
            try:
                from api.websocket.handlers import build_memory_context  # type: ignore
            except Exception:  # pragma: no cover — defensive
                build_memory_context = None  # type: ignore
            if build_memory_context is not None:
                query = _build_memory_query(room_snapshot, prompt)
                if query:
                    memory_context, _ = await build_memory_context(query)
                    if memory_context:
                        payload["memory_context"] = memory_context

        _attach_workspace(payload, room_snapshot.get("workspace_id"))
```

### 3.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -v
```

### 3.5 Commit

```bash
git add backend/src/core/chatroom_orchestrator.py backend/tests/unit/test_chatroom_orchestrator.py
git commit -m "feat(chatroom): inject memory_context into speaking task payload"
```

---

## Task 4: A1 — 触发 schedule_memory_reflection on done

**Goal**: 发言 done 后异步触发反思，`session_id=chatroom:{room_id}`。

### 4.1 写失败测试

```python
@pytest.mark.asyncio
async def test_run_speaking_task_schedules_reflection_on_done(tmp_path, monkeypatch):
    store = ChatroomStore(tmp_path)
    cap = StreamingEchoCapability("assistant")
    cap_registry = CapabilityRegistry()
    cap_registry.register(cap)
    task_registry = TaskRegistry()

    async def fake_build(query: str):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)

    calls: list[dict] = []

    def spy_reflect(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("api.websocket.handlers.schedule_memory_reflection", spy_reflect)

    with patch("core.chatroom_orchestrator._get_capability_registry", return_value=cap_registry), \
         patch("core.chatroom_orchestrator._get_task_registry", return_value=task_registry):
        room = store.create_room(title="t", topic="x", goal="y", members=["assistant"])
        store.add_message(room["id"], sender="user", content="hi")
        task_id = dispatch_speaking_task(room["id"], "assistant", store=store)
        await asyncio.sleep(0.05)
        for _ in range(10):
            if task_registry.get(task_id).status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.05)

    assert len(calls) == 1
    assert calls[0]["session_id"] == f"chatroom:{room['id']}"
    assert calls[0]["source"] == "chatroom:assistant"
```

### 4.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py::test_run_speaking_task_schedules_reflection_on_done -v
```

预期：`assert len(calls) == 1` 失败（实际 0）。

### 4.3 实现

在 `chatroom_orchestrator.py:742` 之后（`_broadcast("chatroom_message_done", ...)` 之后、host_directive 解析之前）：

```python
        # ── A1: 触发记忆反思（不阻塞接力派发） ──
        if auto_memory:
            try:
                from api.websocket.handlers import schedule_memory_reflection  # type: ignore
            except Exception:  # pragma: no cover — defensive
                schedule_memory_reflection = None  # type: ignore
            if schedule_memory_reflection is not None:
                schedule_memory_reflection(
                    user_message=_build_memory_query(room_after, prompt),
                    assistant_text=final_text,
                    source=f"chatroom:{agent_name}",
                    session_id=f"chatroom:{room_id}",
                )
```

注意 `auto_memory` 变量在 Task 3 已声明，需放在同一 try 作用域内可见处。

### 4.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -v
```

### 4.5 Commit

```bash
git add backend/src/core/chatroom_orchestrator.py backend/tests/unit/test_chatroom_orchestrator.py
git commit -m "feat(chatroom): schedule memory reflection on speaking task done"
```

---

## Task 5: A2 — payload 强制 output_format=text（防御性）

**Goal**: payload 写入 `output_format=text`。注意 R1：当前 Agent 不读这个字段，本 Task 是为未来 capability 实现 input override 留口子。

### 5.1 写失败测试

```python
@pytest.mark.asyncio
async def test_run_speaking_task_forces_output_format_text(tmp_path, monkeypatch):
    store = ChatroomStore(tmp_path)
    cap = StreamingEchoCapability("reviewer")
    cap_registry = CapabilityRegistry()
    cap_registry.register(cap)
    task_registry = TaskRegistry()

    async def fake_build(query: str):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)
    monkeypatch.setattr("api.websocket.handlers.schedule_memory_reflection", lambda **kw: None)

    with patch("core.chatroom_orchestrator._get_capability_registry", return_value=cap_registry), \
         patch("core.chatroom_orchestrator._get_task_registry", return_value=task_registry):
        room = store.create_room(title="t", topic="x", goal="y", members=["reviewer"])
        store.add_message(room["id"], sender="user", content="hi")
        task_id = dispatch_speaking_task(room["id"], "reviewer", store=store)
        await asyncio.sleep(0.05)
        for _ in range(10):
            if task_registry.get(task_id).status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.05)

    assert cap.calls[0].get("output_format") == "text"
```

### 5.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py::test_run_speaking_task_forces_output_format_text -v
```

### 5.3 实现

`chatroom_orchestrator.py:585` 附近，注入 memory_context 之后 / `_attach_workspace` 之前：

```python
        # ── A2: 强制群聊文本输出（防御性，当前 Agent 仅在构造时读 output_format，
        # 留 key 待 capability 支持 payload override 时生效；
        # 真正起作用的是下面的 system override 块） ──
        payload["output_format"] = "text"
```

### 5.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -v
```

### 5.5 Commit

```bash
git add backend/src/core/chatroom_orchestrator.py backend/tests/unit/test_chatroom_orchestrator.py
git commit -m "feat(chatroom): force output_format=text in payload (defensive, primary fix is system override)"
```

---

## Task 6: A2 — 插入聊天室协作模式 system 块覆盖 JSON 契约

**Goal**: `messages[0]` 强插一个 system 块覆盖 yaml 中 reviewer/coder/planner 的 JSON 输出契约。这是 A2 的真正修复。

### 6.1 写失败测试

```python
@pytest.mark.asyncio
async def test_run_speaking_task_inserts_chatroom_override_system(tmp_path, monkeypatch):
    store = ChatroomStore(tmp_path)
    cap = StreamingEchoCapability("reviewer")
    cap_registry = CapabilityRegistry()
    cap_registry.register(cap)
    task_registry = TaskRegistry()

    async def fake_build(query: str):
        return ("", 0)

    monkeypatch.setattr("api.websocket.handlers.build_memory_context", fake_build)
    monkeypatch.setattr("api.websocket.handlers.schedule_memory_reflection", lambda **kw: None)

    with patch("core.chatroom_orchestrator._get_capability_registry", return_value=cap_registry), \
         patch("core.chatroom_orchestrator._get_task_registry", return_value=task_registry):
        room = store.create_room(title="t", topic="x", goal="y", members=["reviewer"])
        store.add_message(room["id"], sender="user", content="hi")
        task_id = dispatch_speaking_task(room["id"], "reviewer", store=store)
        await asyncio.sleep(0.05)
        for _ in range(10):
            if task_registry.get(task_id).status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            await asyncio.sleep(0.05)

    msgs = cap.calls[0]["messages"]
    assert msgs[0]["role"] == "system"
    assert "聊天室协作模式" in msgs[0]["content"]
    # build_room_context 原本的 system 块应仍存在（topic / goal / 历史）
    body_systems = [m for m in msgs[1:] if m.get("role") == "system"]
    assert any("[房间主题]" in (m.get("content") or "") for m in body_systems)
```

### 6.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py::test_run_speaking_task_inserts_chatroom_override_system -v
```

### 6.3 实现

`chatroom_orchestrator.py` 顶部 imports 之后（约 line 60）新增模块常量：

```python
_CHATROOM_OVERRIDE_PROMPT = (
    "【聊天室协作模式】\n"
    "你正在多 Agent 群聊里发言，不是在跑工作流任务。请遵守以下规则，"
    "它们覆盖你原始 system prompt 中的输出契约：\n"
    "- 用普通自然语言回复，markdown 自由用。\n"
    "- 不要输出纯 JSON、不要包结构化字段（除非另一成员明确要求结构化结果）。\n"
    "- 想接力就用 `@成员名`；不想接力就别 @。\n"
    "- 保持简洁，一两段话足够，避免长篇大论。\n"
    "- 例外：你若是该房间主持人（auto_host），按已有 host_directive 协议在末尾给 JSON 代码块。"
)
```

修改 `_run_speaking_task:577` 把 `build_room_context` 的返回插入覆盖块：

```python
        context_messages = build_room_context(room_snapshot, agent_name)
        context_messages.insert(0, {
            "role": "system",
            "content": _CHATROOM_OVERRIDE_PROMPT,
        })
```

### 6.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_chatroom_orchestrator.py -v
```

### 6.5 Commit

```bash
git add backend/src/core/chatroom_orchestrator.py backend/tests/unit/test_chatroom_orchestrator.py
git commit -m "feat(chatroom): prepend override system prompt to suppress JSON contract in groupchat"
```

---

## Task 7: A6 — `core/llm/retry.py` 装饰器

**Goal**: 独立 helper：分类瞬态错误 + 指数退避 + jitter + on_retry 回调。

### 7.1 写失败测试

新建 `backend/tests/unit/test_llm_retry.py`：

```python
"""单测：core.llm.retry.call_with_retry."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.retry import call_with_retry, _is_retryable


class _FakeAPIError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status={status_code}")
        self.status_code = status_code


class _FakeRateLimit(Exception):
    pass


# 给 _is_retryable 用的伪类型名匹配
_FakeRateLimit.__name__ = "RateLimitError"


@pytest.mark.asyncio
async def test_returns_on_first_success():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "ok"

    out = await call_with_retry(fn, max_retries=3, initial_delay=0.0)
    assert out == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_retries_on_connection_error(monkeypatch):
    class _ConnErr(Exception):
        pass
    _ConnErr.__name__ = "APIConnectionError"

    attempts = 0
    seen = []

    async def fn():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _ConnErr("boom")
        return "ok"

    def on_retry(att, exc, sleep):
        seen.append((att, type(exc).__name__))

    out = await call_with_retry(fn, max_retries=3, initial_delay=0.0, on_retry=on_retry)
    assert out == "ok"
    assert attempts == 3
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_does_not_retry_on_4xx():
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise _FakeAPIError(400)

    with pytest.raises(_FakeAPIError):
        await call_with_retry(fn, max_retries=3, initial_delay=0.0)
    assert calls == 1


@pytest.mark.asyncio
async def test_exhausts_and_raises():
    calls = 0
    seen: list = []

    async def fn():
        nonlocal calls
        calls += 1
        raise _FakeRateLimit("slow down")

    with pytest.raises(_FakeRateLimit):
        await call_with_retry(
            fn, max_retries=3, initial_delay=0.0,
            on_retry=lambda a, e, s: seen.append(a),
        )
    assert calls == 4  # 首发 + 3 次重试
    assert seen == [1, 2, 3]


@pytest.mark.asyncio
async def test_jitter_within_20_percent(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("core.llm.retry.random.random", lambda: 0.5)  # 中点 → 1.0x

    class _Conn(Exception):
        pass
    _Conn.__name__ = "APIConnectionError"

    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _Conn("x")
        return "ok"

    await call_with_retry(fn, max_retries=3, initial_delay=1.0)
    # delay 序列：1.0 → 2.0；jitter=0.8+0.4*0.5=1.0 → 不偏移
    assert sleeps == [1.0, 2.0]


def test_is_retryable_5xx():
    err = _FakeAPIError(503)
    assert _is_retryable(err)


def test_is_retryable_4xx_false():
    err = _FakeAPIError(400)
    assert not _is_retryable(err)


def test_is_retryable_unknown_false():
    assert not _is_retryable(ValueError("nope"))
```

### 7.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_llm_retry.py -v
```

预期：`ImportError: No module named 'core.llm.retry'`。

### 7.3 实现

新建 `backend/src/core/llm/retry.py`：

```python
"""LLM 调用重试 helper。

捕获瞬态错误（APIConnectionError / APITimeoutError / RateLimitError /
5xx APIError），指数退避 + ±20% jitter 重试。其他错误（4xx 非 429、
auth、bad-request）直接 raise，不重试。

延迟 import 避免单测时 anthropic / openai 缺失。
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional


def _is_retryable(exc: BaseException) -> bool:
    """根据异常类型名 + status_code 判断是否瞬态可重试。"""
    name = type(exc).__name__
    if name in ("APIConnectionError", "APITimeoutError", "RateLimitError"):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and 500 <= status < 600:
        return True
    return False


async def call_with_retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> Any:
    """指数退避调用 ``fn``。

    Args:
        fn: 无参 async callable。
        max_retries: 不含首发的最大重试次数。
        initial_delay: 首次退避秒数；之后 ×2 + ±20% jitter。
        on_retry: 每次重试前的同步回调 ``(attempt, exc, sleep_for)``。
                  attempt 从 1 开始计数。

    Returns:
        ``fn`` 的返回值。

    Raises:
        最后一次尝试的原异常（不重试时立即抛）。
    """
    delay = initial_delay
    attempt = 0
    while True:
        try:
            return await fn()
        except BaseException as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            jitter = delay * (0.8 + 0.4 * random.random())  # ±20%
            if on_retry is not None:
                try:
                    on_retry(attempt + 1, exc, jitter)
                except Exception:  # pragma: no cover — 回调异常不影响主流程
                    pass
            await asyncio.sleep(jitter)
            attempt += 1
            delay *= 2
```

### 7.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_llm_retry.py -v
```

### 7.5 Commit

```bash
git add backend/src/core/llm/retry.py backend/tests/unit/test_llm_retry.py
git commit -m "feat(llm): add call_with_retry helper with exponential backoff"
```

---

## Task 8: A6 — config/system.yaml 加重试配置

**Goal**: 顶层 `llm:` 段加 `max_retries` / `retry_initial_delay`。

### 8.1 写失败测试

`backend/tests/unit/test_config.py` 新增：

```python
def test_system_yaml_has_llm_retry_config():
    """A6: system.yaml 应暴露重试配置。"""
    import yaml
    from pathlib import Path
    root = Path(__file__).parent.parent.parent.parent
    data = yaml.safe_load((root / "config" / "system.yaml").read_text(encoding="utf-8"))
    llm_cfg = data.get("llm") or {}
    assert "max_retries" in llm_cfg
    assert isinstance(llm_cfg["max_retries"], int) and llm_cfg["max_retries"] >= 0
    assert "retry_initial_delay" in llm_cfg
```

### 8.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_config.py::test_system_yaml_has_llm_retry_config -v
```

### 8.3 实现

`config/system.yaml` 在 `llm:` 段（约 line 32）新增字段：

```yaml
llm:
  provider: "openai"
  api_key: ""
  model: "gpt-3.5-turbo"
  base_url: "https://cpa.chordvers.org/v1"
  temperature: 0.7
  top_p: null
  max_tokens: 4096
  stop_sequences: []
  max_retries: 3                # A6: 总重试次数（不含首发），瞬态错误才重试
  retry_initial_delay: 1.0      # A6: 首次退避秒数；之后 ×2 + ±20% jitter
  openai:
    ...
```

### 8.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_config.py -v
```

### 8.5 Commit

```bash
git add config/system.yaml backend/tests/unit/test_config.py
git commit -m "feat(config): add llm.max_retries / retry_initial_delay defaults"
```

---

## Task 9: A6 — `BaseLLMClient` 加 `on_retry` 参数

**Goal**: `chat` / `chat_stream` 签名加 `on_retry: Optional[Callable] = None`。子类向后兼容。

### 9.1 写失败测试

`backend/tests/unit/test_channels_and_anthropic.py` 或新建 `test_llm_base_signature.py`：

```python
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.base import BaseLLMClient


def test_chat_signature_has_on_retry():
    sig = inspect.signature(BaseLLMClient.chat)
    assert "on_retry" in sig.parameters


def test_chat_stream_signature_has_on_retry():
    sig = inspect.signature(BaseLLMClient.chat_stream)
    assert "on_retry" in sig.parameters
```

### 9.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_llm_base_signature.py -v
```

### 9.3 实现

`backend/src/core/llm/base.py` 修改：

```python
class BaseLLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
        on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    ) -> LLMResponse:
        """发送聊天消息，可选传入工具定义和重试回调。"""

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
        on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """流式聊天 — on_retry 仅作用于 stream 建立连接前的瞬态错误。"""
        response = await self.chat(messages, tools, on_retry=on_retry)
        ...
```

需要在文件顶部 `from typing import ...` 加 `Callable`。

### 9.4 跑通过

```bash
python3 -m pytest backend/tests/unit/ -v -k "llm or channels"
```

### 9.5 Commit

```bash
git add backend/src/core/llm/base.py backend/tests/unit/test_llm_base_signature.py
git commit -m "feat(llm): add on_retry kwarg to BaseLLMClient.chat / chat_stream"
```

---

## Task 10: A6 — OpenAIClient 接入 call_with_retry

**Goal**: `OpenAIClient.chat` / `chat_stream` 用 `call_with_retry` 包 `_create_with_compat_retry`，从 settings 读 `max_retries` / `retry_initial_delay`。

### 10.1 写失败测试

新建 `backend/tests/integration/test_llm_client_retry.py`：

```python
"""集成测试：OpenAI / Anthropic 客户端接入 call_with_retry。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.llm.openai_client import OpenAIClient


class _ConnErr(Exception):
    pass

_ConnErr.__name__ = "APIConnectionError"


@pytest.mark.asyncio
async def test_openai_chat_retries_on_connection_error(monkeypatch):
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-3.5-turbo"
    client.client = MagicMock()
    client._max_retries = 3
    client._retry_initial_delay = 0.0  # 单测加速

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="hi", tool_calls=None))]
    fake_resp.usage = None

    calls = 0

    async def fake_create(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _ConnErr("boom")
        return fake_resp

    client.client.chat.completions.create = fake_create

    # _request_options / _convert_messages 走默认实现
    monkeypatch.setattr(OpenAIClient, "_request_options", lambda self: {})

    out = await client.chat([{"role": "user", "content": "hi"}])
    assert out.content == "hi"
    assert calls == 3
```

（anthropic 同模式略，以及一个 `test_chat_stream_does_not_retry_mid_stream`。）

### 10.2 跑失败

```bash
python3 -m pytest backend/tests/integration/test_llm_client_retry.py -v
```

### 10.3 实现

`backend/src/core/llm/openai_client.py`：

`__init__`（找现成构造，约 line 30-50）增加：

```python
        # A6: 重试配置（来自 system.yaml.llm）
        retry_cfg = (config or {}).get("retry") or {}
        self._max_retries = int(retry_cfg.get("max_retries", 3))
        self._retry_initial_delay = float(retry_cfg.get("initial_delay", 1.0))
```

（如果当前 `config` 字典是顶层 `llm` 段，则直接读 `config.get("max_retries", 3)` / `config.get("retry_initial_delay", 1.0)` — 实现时先 grep 确认 OpenAIClient 的 `__init__` 怎么读 config。）

`chat`（line 75）：

```python
        from .retry import call_with_retry  # 局部 import 防循环

        start = time.perf_counter()
        response = await call_with_retry(
            lambda: self._create_with_compat_retry(kwargs),
            max_retries=self._max_retries,
            initial_delay=self._retry_initial_delay,
            on_retry=on_retry,
        )
        parsed = self._parse_response(response)
        parsed.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return parsed
```

`chat_stream`（line 165 / 169）：仅"建立流连接"那次包 `call_with_retry`：

```python
        from .retry import call_with_retry

        async def _open_stream():
            try:
                return await self._create_with_compat_retry(kwargs)
            except Exception:
                kwargs.pop("stream_options", None)
                return await self._create_with_compat_retry(kwargs)

        stream = await call_with_retry(
            _open_stream,
            max_retries=self._max_retries,
            initial_delay=self._retry_initial_delay,
            on_retry=on_retry,
        )
        # 进入 async for 后不重试（spec §4.2(f)）
```

加 `on_retry` 形参到 `chat` / `chat_stream`。

### 10.4 跑通过

```bash
python3 -m pytest backend/tests/integration/test_llm_client_retry.py -v
python3 -m pytest backend/tests/ -q
```

### 10.5 Commit

```bash
git add backend/src/core/llm/openai_client.py backend/tests/integration/test_llm_client_retry.py
git commit -m "feat(llm): wrap OpenAIClient calls with call_with_retry"
```

---

## Task 11: A6 — AnthropicClient 接入 call_with_retry

**Goal**: 同 Task 10 接入 Anthropic 客户端。`chat`（line 102）和 `chat_stream`（line 218）的 `client.messages.create` 都用 `call_with_retry` 包。

### 11.1 写失败测试

`test_llm_client_retry.py` 新增 `test_anthropic_chat_retries_on_rate_limit`，结构同 Task 10。

### 11.2 跑失败

```bash
python3 -m pytest backend/tests/integration/test_llm_client_retry.py::test_anthropic_chat_retries_on_rate_limit -v
```

### 11.3 实现

`backend/src/core/llm/anthropic_client.py`：

`__init__` 加同样的 `_max_retries` / `_retry_initial_delay`。

`chat`（line 101-105）：

```python
        from .retry import call_with_retry

        start = time.perf_counter()
        response = await call_with_retry(
            lambda: self.client.messages.create(**kwargs),
            max_retries=self._max_retries,
            initial_delay=self._retry_initial_delay,
            on_retry=on_retry,
        )
        parsed = self._parse_response(response)
        parsed.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return parsed
```

`chat_stream` 同步处理：仅在建立 stream 时重试。

### 11.4 跑通过

```bash
python3 -m pytest backend/tests/integration/test_llm_client_retry.py -v
```

### 11.5 Commit

```bash
git add backend/src/core/llm/anthropic_client.py backend/tests/integration/test_llm_client_retry.py
git commit -m "feat(llm): wrap AnthropicClient calls with call_with_retry"
```

---

## Task 12: A6 — `AgentProgress.retry_count` 字段 + 覆盖式 merge

**Goal**: `AgentProgress` 新增 `retry_count: int = 0`；`_merge_progress` 用覆盖语义（区别于累加字段）。

### 12.1 写失败测试

`backend/tests/unit/test_task_registry.py`（如果存在）或新建 `test_agent_progress_retry.py`：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.task.registry import TaskRegistry
from core.task.types import AgentProgress, TaskType


def test_agent_progress_has_retry_count_default_zero():
    p = AgentProgress()
    assert p.retry_count == 0
    assert "retry_count" in p.to_dict()


def test_set_progress_retry_count_is_overwrite_not_accumulate():
    reg = TaskRegistry()
    state = reg.create(type=TaskType.AGENT_RUN, requirement="g")
    reg.set_progress(state.id, retry_count=2)
    assert reg.get(state.id).progress.retry_count == 2
    reg.set_progress(state.id, retry_count=3)
    assert reg.get(state.id).progress.retry_count == 3  # 覆盖而非累加
    reg.set_progress(state.id, retry_count=0)
    assert reg.get(state.id).progress.retry_count == 0  # 重置
```

### 12.2 跑失败

```bash
python3 -m pytest backend/tests/unit/test_agent_progress_retry.py -v
```

### 12.3 实现

`backend/src/core/task/types.py:42-57`：

```python
@dataclass
class AgentProgress:
    tool_count: int = 0
    total_tokens: int = 0
    activity: str = ""
    last_tool: Optional[str] = None
    current_step: Optional[str] = None
    memory_count: int = 0
    retry_count: int = 0  # A6: 当前正在重试的尝试号；覆盖语义，重试成功后调用方显式置 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

`backend/src/core/task/registry.py:217-230` 在 `_merge_progress` 末尾新增：

```python
        if "retry_count" in delta and delta["retry_count"] is not None:
            progress.retry_count = int(delta["retry_count"])  # A6: 覆盖（最新尝试号）
```

### 12.4 跑通过

```bash
python3 -m pytest backend/tests/unit/test_agent_progress_retry.py backend/tests/unit/ -v -k "task or progress"
```

### 12.5 Commit

```bash
git add backend/src/core/task/types.py backend/src/core/task/registry.py backend/tests/unit/test_agent_progress_retry.py
git commit -m "feat(task): add AgentProgress.retry_count with overwrite semantics"
```

---

## Task 13: A6 — Agent 注入 on_retry 闭包

**Goal**: `Agent.run` / `run_stream` 在调 LLM 前用 contextvar 取 `task_id`，构造 `on_retry(attempt, exc, sleep_for)` 闭包，通过 `task_registry.set_progress(retry_count=attempt, activity=f"重试中 ({attempt}/{max_retries})")` 推前端。

### 13.1 写失败测试

```python
@pytest.mark.asyncio
async def test_agent_emits_retry_progress_via_on_retry(monkeypatch):
    """Agent 在 LLM 抛瞬态错误时，应通过 on_retry 推 progress.retry_count。"""
    # 构造一个 fake LLM，chat 抛 _ConnErr 两次后成功；
    # 拦 set_progress 调用，断言 retry_count=1 / 2 顺序
    ...
```

（实现细节较长，复用 `test_agent_loop_phase_a.py` 的 mock 风格。）

### 13.2 跑失败

### 13.3 实现

`backend/src/core/agent/agent.py:122` 调 LLM 前：

```python
                # A6: 注入 on_retry 闭包推 progress（仅当任务上下文存在）
                on_retry_cb = self._build_on_retry_callback()
                response = await self.llm.chat(
                    messages,
                    tools=tool_schemas if tool_schemas else None,
                    on_retry=on_retry_cb,
                )
                # 调用成功 → 重置 retry_count
                self._reset_retry_progress()
```

新增 helper：

```python
    def _build_on_retry_callback(self):
        from core.task import current_task_id  # contextvar
        from api.dependencies import get_task_registry
        try:
            task_id = current_task_id()
        except Exception:
            return None
        if not task_id:
            return None
        registry = get_task_registry()
        if registry is None:
            return None
        max_retries = self._runtime_config.get("max_retries", 3)

        def _on_retry(attempt: int, exc: BaseException, sleep_for: float) -> None:
            registry.set_progress(
                task_id,
                retry_count=attempt,
                activity=f"重试中 ({attempt}/{max_retries})",
            )
        return _on_retry

    def _reset_retry_progress(self):
        # 调成功后置 0，避免前端卡在"重试中"
        ...
```

注：`current_task_id` contextvar 的具体名字以代码实际为准，先 grep `current_task` / `parent_task_id` 确认。

### 13.4 跑通过

```bash
python3 -m pytest backend/tests/ -q
```

### 13.5 Commit

```bash
git add backend/src/core/agent/agent.py backend/tests/unit/test_agent_retry_progress.py
git commit -m "feat(agent): emit progress.retry_count via on_retry callback"
```

---

## Task 14: A6 — 前端 RunsPanel 显示"重试中" 徽标

**Goal**: TypeScript 类型加 `retry_count`；卡片在 `retry_count > 0 && status==='running'` 时显示徽标。

### 14.1 写失败测试

前端无 jest 测试体系。手工浏览器验证为主，配 build check：

```bash
cd frontend && npm run build
```

加一个 type-only 检查：在 `frontend/src/types/index.ts` 改后跑 `tsc --noEmit`。

### 14.2 实现

`frontend/src/types/index.ts` 找 `AgentProgress` interface 加：

```typescript
export interface AgentProgress {
  tool_count?: number
  total_tokens?: number
  activity?: string
  last_tool?: string | null
  current_step?: string | null
  memory_count?: number
  retry_count?: number  // A6: 当前重试尝试号；> 0 表示正在重试
}
```

`frontend/src/components/RunsPanel.tsx:380-390` 卡片渲染区加徽标：

```tsx
{run.progress?.retry_count != null && run.progress.retry_count > 0 && run.status === 'running' && (
  <span className="run-card__retry-badge">
    重试中 {run.progress.retry_count}/{maxRetries}
  </span>
)}
```

`maxRetries` 暂时硬编码 3 或从 settings 取。

`frontend/src/components/RunsPanel.css` 加：

```css
.run-card__retry-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background: var(--color-warning-bg, #fff7e6);
  color: var(--color-warning-fg, #d46b08);
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
}
```

### 14.3 验证

```bash
cd frontend && npm run build
```

无 TS 错误，bundle 产出正常。

### 14.4 Commit

```bash
git add frontend/src/types/index.ts frontend/src/components/RunsPanel.tsx frontend/src/components/RunsPanel.css
git commit -m "feat(ui): show retrying badge in RunsPanel based on progress.retry_count"
```

---

## Task 15: A6 — ChatroomPanel 流式中断文案

**Goal**: 既有 `chatroom-msg__retry`（line 1082-1093）的"调用失败"文案区分"流式中断"和"其他错误"。Spec §R2 显式取舍，需让用户知道点击重试。

### 15.1 实现

`frontend/src/components/ChatroomPanel.tsx:1083-1086`：

```tsx
{message.status === 'failed' && (
  <div className="chatroom-msg__retry">
    <span className="chatroom-msg__error">
      {(meta.error as string)?.includes('Stream') || (meta.error as string)?.includes('stream')
        ? '流式中断，请点击重试'
        : ((meta.error as string) || '调用失败')}
    </span>
    {isAgent && (
      <button type="button" className="btn-xs" onClick={() => onRetry(message)}>
        重试
      </button>
    )}
  </div>
)}
```

### 15.2 验证

`npm run build` 无错。

### 15.3 Commit

```bash
git add frontend/src/components/ChatroomPanel.tsx
git commit -m "feat(ui): clarify stream-interruption error message in ChatroomPanel"
```

---

## Task 16: 回归整合测试

**Goal**: 跑完整 backend 测试 + frontend build，确认 A1 / A2 / A6 三块互不破坏。

### 16.1 步骤

```bash
# 1. 后端全量
python3 -m pytest backend/tests/ -q

# 2. 关注的子集
python3 -m pytest backend/tests/unit/test_chatroom.py \
                  backend/tests/unit/test_chatroom_orchestrator.py \
                  backend/tests/unit/test_llm_retry.py \
                  backend/tests/unit/test_agent_progress_retry.py \
                  backend/tests/integration/test_llm_client_retry.py -v

# 3. 前端
cd frontend && npm run build && cd ..
```

### 16.2 手工验证脚本（选做）

依次跑下面 4 步，确认整条链路：

1. **A1**：启服务 → ChatPanel 跟 assistant 说"我喜欢喝美式"→ 创建带 assistant 的房间 → 问"你记得我喝什么吗" → 后端日志应有 `[MEMORY] recalled N memories`，回复出现"美式"。
2. **A2**：房间含 reviewer → 用户发"@reviewer 你今天心情如何" → 回复是中文段落而非 `{"approved": ...}`。
3. **A6**：把 `config.yaml` 的 `base_url` 改到 502 端点 → 发消息 → 日志看到 1s/2s/4s 重试 → 前端卡片"重试中 1/3 → 2/3 → 失败"。
4. **回归**：`POST /api/agents/reviewer/invoke {data:{code:"def x(): pass"}}` → ChatPanel 路径仍是 JSON 契约。

### 16.3 Commit

无代码改动则跳过。如有微调 commit 一次。

---

## Task 17: 文档同步

**Goal**: 更新 `agentic-system/CLAUDE.md` 状态表 + 必要章节，让后续 AI / 开发者知道 A1/A2/A6 已落地。

### 17.1 实现

`agentic-system/CLAUDE.md` 1.2 节状态表新增/更新：

```markdown
| 长期记忆系统 | ✅ 已实现（含聊天室路径，A1） | 情景/语义/程序记忆，InMemory + ChromaDB；ChatPanel / Agent Run / Chatroom 全链路注入与反思 |
| LLM 调用真重试 | ✅ 已实现（A6） | call_with_retry 指数退避 + jitter；前端 RunsPanel 显示重试中徽标 |
```

3.10 节 Chatroom 添加：

```markdown
**长期记忆**：每个 speaking task 自动调 `build_memory_context` 注入 `memory_context`，done 后非阻塞触发 `schedule_memory_reflection`，session_id 为 `chatroom:{room_id}`。可通过 `Chatroom.settings.auto_memory=False` 关闭。

**输出契约覆盖**：`_run_speaking_task` 在 messages 第 0 块插入聊天室协作模式 system，覆盖 yaml 中 reviewer/coder/planner 的 JSON 契约（不动 yaml 本体保护工作流路径）。
```

3.4 / 3.5 节 LLM 段补：

```markdown
**重试**：所有 LLM 调用经 `core/llm/retry.py:call_with_retry` 包装；瞬态错误（5xx / 网络 / RateLimit）按 `system.yaml.llm.max_retries` 指数退避重试；流式中途断开不重试。`AgentProgress.retry_count` 是覆盖语义。
```

### 17.2 验证

人工读，结构无破坏。

### 17.3 Commit

```bash
git add agentic-system/CLAUDE.md
git commit -m "docs: sync CLAUDE.md with A1 / A2 / A6 bug fixes"
```

---

## Task 18: A5 占位说明

**Goal**: 在 `docs/superpowers/specs/2026-05-28-urgent-bugfix-design.md` §3 已经写明 A5 不实施。本期不动任何代码，仅在 plan 末尾留 traceback：

- `chatroom_orchestrator.py:838-933` 的 `_parse_host_directive` / `_extract_json_object` 保留。
- `routes/chatrooms.py:182-207` auto_host 注入 host_prompt 文本保留。
- 等 Spec 2 落地 `chatroom_dispatch` 工具替换整套基于文本的 host_directive 协议。

本 plan 不为 A5 创建任何 task，仅在 Task 6 的覆盖 prompt 中保留 host_directive 例外条款（"你若是该房间主持人（auto_host），按已有 host_directive 协议在末尾给 JSON 代码块"），确保 auto_host 主持人在协议被替换前仍能正常工作。

无 commit。

---

## 整体验证脚本

最后一次 commit 之前跑：

```bash
python3 -m pytest backend/tests/ -q
cd frontend && npm run build && cd ..
git log --oneline -20
```

确认 commits 顺序合理、无 WIP，文档同步在最后一笔。

---

## 实施顺序与依赖

| Task | 模块 | 依赖 | 备注 |
|------|------|------|------|
| 1 | A1 chatroom defaults | — | |
| 2 | A1 _build_memory_query | 1 | |
| 3 | A1 inject memory_context | 2 | |
| 4 | A1 schedule reflection | 3 | |
| 5 | A2 force output_format | 4 | 防御性，Task 6 是真修复 |
| 6 | A2 system override | 5 | |
| 7 | A6 retry helper | — | 与 A1/A2 并行 |
| 8 | A6 system.yaml | 7 | |
| 9 | A6 BaseLLMClient sig | 7 | |
| 10 | A6 OpenAI 接入 | 8, 9 | |
| 11 | A6 Anthropic 接入 | 10 | |
| 12 | A6 retry_count field | 11 | |
| 13 | A6 Agent on_retry | 12 | |
| 14 | A6 RunsPanel UI | 12, 13 | |
| 15 | A6 ChatroomPanel 文案 | 14 | |
| 16 | 整合测试 | 15 | |
| 17 | 文档同步 | 16 | |
| 18 | A5 占位说明 | — | 无代码 |

A1 / A6 两条线在 Task 7 之前可并行（它们改不同文件）。Task 14 / 15 为前端，需后端 Task 13 完成后才能联调。

---

## 验收标准

1. `python3 -m pytest backend/tests/ -q` 全绿，新增 ~15 个测试用例都通过。
2. `cd frontend && npm run build` 无 TypeScript 错。
3. 手工流程 4 步全过（Task 16.2）。
4. CLAUDE.md 状态表更新；A5 占位文字清楚标注"延后 Spec 2"。
5. Commit 历史按 spec § 提交规范（`feat:` / `fix:` / `docs:` / `test:`）。
