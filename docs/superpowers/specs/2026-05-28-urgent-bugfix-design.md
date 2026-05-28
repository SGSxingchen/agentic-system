# 紧急 Bug 修复设计 — 2026-05-28

> 4 项紧急 bug 修复设计：A1 聊天室记忆 / A2 闲聊 JSON / A5 占位 / A6 LLM 重试。
> 不实现新功能，只修复已暴露的故障。设计哲学：**补全而非添加**——别给 Agent 戴枷锁，
> 默认放开能力，谁要锁谁自己加规则。

涉及文件锚点（行号基于当前 `feature/agent-chatroom` 分支）：

- `backend/src/core/chatroom_orchestrator.py`（933 行）
- `backend/src/core/chatroom.py`（834 行）
- `backend/src/api/routes/chatrooms.py`（297 行）
- `backend/src/api/routes/tasks.py`（885 行）
- `backend/src/api/routes/agents.py`（1062 行）
- `backend/src/api/websocket/handlers.py`（750 行）
- `backend/src/core/llm/openai_client.py`（375 行）
- `backend/src/core/llm/anthropic_client.py`（355 行）
- `backend/src/core/task/types.py`（`AgentProgress`, `TaskState`）
- `config/agents.yaml` / `config/system.yaml`

---

## 1. A1：聊天室记忆补齐

### 1.1 现状

聊天室派发路径完全没接长期记忆。`chatroom_orchestrator._run_speaking_task`
在 `chatroom_orchestrator.py:579-585` 拼 payload：

```python
payload: Dict[str, Any] = {
    "messages": context_messages,
    "message": prompt or "请发言",
    "task_id": task_id,
}
_attach_workspace(payload, room_snapshot.get("workspace_id"))
```

既没调 `build_memory_context`，也没在 `done` 之后调 `schedule_memory_reflection`。

对比已有实现：

- Agent Run 路径 `routes/tasks.py:275-281` 通过 `build_memory_context(_memory_query(...))`
  注入 `memory_context`；`tasks.py:562-568` 触发 `schedule_memory_reflection`。
- ChatPanel 路径 `routes/agents.py:1046-1057` 同理：先 `build_memory_context(message)`
  注入，再 `schedule_memory_reflection(...)`。
- WebSocket 直聊路径 `websocket/handlers.py:336/353-354/376/570` 也都接了。

聊天室是唯一的漏网之鱼。

### 1.2 修法

**(a) settings 默认值**

`core/chatroom.py:38-46` 的 `DEFAULT_SETTINGS` 新增 `"auto_memory": True`。
房间级别可关；不动全局开关——现在没必要再加一层。

**(b) 注入位置**

修改 `_run_speaking_task`（`chatroom_orchestrator.py:507-690`）。在拼完
`context_messages` 之后、调 `_attach_workspace` 之前插入 query 拼装与 memory 注入：

```python
# anchor: chatroom_orchestrator.py:579 之前
auto_memory = bool((room_snapshot.get("settings") or {}).get("auto_memory", True))
memory_count = 0
if auto_memory:
    query = _build_memory_query(room_snapshot, prompt)
    memory_context, memory_count = await build_memory_context(query)
    if memory_context:
        payload["memory_context"] = memory_context
```

`build_memory_context` 从 `api.websocket.handlers` 顶部导入；和 `_broadcast`
同样走"运行时 import 防循环"——必要时用 try/except 包一层。

**(c) query 拼装函数（草稿）**

新增模块函数（放 `chatroom_orchestrator.py` 工具函数区，靠近 `_truncate`）：

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
    if prompt:
        parts.append(prompt.strip())
    return "\n".join(parts)
```

返回空串时 `build_memory_context` 自身会短路（参见 `handlers.py:598-599`）。

**(d) 反思触发位置**

`_run_speaking_task` 的 done 处理段（`chatroom_orchestrator.py:691-742`，目前在
`store.update_message(... status="done")` 之后）追加：

```python
# anchor: chatroom_orchestrator.py:742 之后、host_directive 解析之前
if auto_memory:
    schedule_memory_reflection(
        user_message=_build_memory_query(room_after, prompt),
        assistant_text=final_text,
        source=f"chatroom:{agent_name}",
        session_id=f"chatroom:{room_id}",
    )
```

`session_id=chatroom:{room_id}` 是关键：所有该房间的 reflection 在同一会话维度
下沉淀，便于事后定位"哪个房间留下的记忆"。

**接力场景**：每个 Agent 发言完 done 都会执行这段，所以 N 个 Agent 接力 = N 次反思，
天然满足"每个 Agent 都做自己的反思"。`schedule_memory_reflection` 已是非阻塞（背景
asyncio.create_task），不影响接力派发节奏。

### 1.3 影响范围

**改动文件**：
- `backend/src/core/chatroom.py` — 仅改 DEFAULT_SETTINGS
- `backend/src/core/chatroom_orchestrator.py` — 新增 `_build_memory_query` + 两处注入
- 不动 `routes/chatrooms.py`（HTTP 层无关）

**潜在副作用**：
- 房间历史长时拉 3 条尾巴 + prompt 可能 > 1KB，`build_memory_context` 内部对长 query
  没截断，若 embedding provider 有上限需观察；当前 OpenAI text-embedding 上限
  ~8K tokens，3 条 + prompt 远低于阈值。
- reflection 的 `MemoryProcessor.process_conversation` 期望"user/assistant 一问一答"，
  房间 query 是聚合文本不是对话。**这是已知简化**——`_memory_query`/`source` 等价
  Agent Run 路径已经这么用了，行为一致即可。

### 1.4 测试

**单元测试**（`backend/tests/unit/test_chatroom_orchestrator.py` 新增 case）：

1. `test_run_speaking_task_injects_memory_context_when_auto_memory_true`：
   monkeypatch `build_memory_context` 返回 `("[mem] foo", 1)`，断言 capability
   收到的 payload 含 `memory_context`。
2. `test_run_speaking_task_skips_memory_when_auto_memory_false`：
   `update_room(room_id, settings={"auto_memory": False})` 后断言不调
   `build_memory_context`。
3. `test_run_speaking_task_schedules_reflection_on_done`：
   monkeypatch `schedule_memory_reflection` 为 spy，断言被调一次且
   `session_id == f"chatroom:{room_id}"`。
4. `test_build_memory_query_takes_last_three_messages`：纯函数测试，3 条尾巴 + prompt 顺序拼接。

**手工验证**：
1. 启动后端 + 前端，先在 ChatPanel 跟 assistant 说"我喜欢喝美式"，观察
   `[MEMORY] reflected chat window` 日志写入一条记忆。
2. 创建带 assistant 的房间，问"你记得我喝什么吗"，断言：
   - 后端日志 `[MEMORY] recalled N memories for query=...`
   - 回复正文出现"美式"。
3. 关闭房间 settings.auto_memory，重复 step 2，断言无 `[MEMORY] recalled` 日志。

---

## 2. A2：聊天室强制覆盖输出格式

### 2.1 现状

`config/agents.yaml` 中 planner / coder / reviewer 三个 Agent 都写了：

- `output_format: json`（agents.yaml:204 / 250 / 301）
- system_prompt 末尾"输出契约：严格输出纯 JSON，不输出 markdown，不输出解释文字。"
  （agents.yaml:186 / 228 / 277）

聊天室直接复用同一 capability，所以闲聊场景下 reviewer 被 @ 也会吐
`{"approved": true, "issues": [...]}` 这种工作流契约 JSON。在群聊里完全是噪音。

Agent Run 路径与 ChatPanel 路径需要保留 JSON 契约（结构化下游消费），所以
**不能改 yaml 本体**。

### 2.2 修法

**落点**：`chatroom_orchestrator._run_speaking_task` 拼 payload 时强制覆盖。

**(a) 强制 output_format=text**

`payload` 字典已经在 `chatroom_orchestrator.py:579-585` 构造，新增：

```python
# anchor: chatroom_orchestrator.py:585 之后
payload["output_format"] = "text"  # 群聊强制文本输出，覆盖 yaml 中的 json 契约
```

是否生效取决于 capability 的实现：当前 `core.agent.Agent` 在
`core.agent.runtime` / `agent.py` 内部读 payload['output_format']` 决定是否拼"严格
JSON"片段。**如果 capability 不读这个字段**，则只靠 (b) 的 system override 兜底，
该 key 也无害。修复时应顺手 grep 确认（`grep -rn "output_format" backend/src/core/agent/`）。

**(b) System messages 第 0 块插入"聊天室协作模式"覆盖前缀**

在 `build_room_context` 返回的 messages 之前再加一层 system："覆盖"原 yaml prompt 的
JSON 契约。改 `_run_speaking_task` 中调用点：

```python
# anchor: chatroom_orchestrator.py:577 替换 build_room_context 调用
context_messages = build_room_context(room_snapshot, agent_name)
context_messages.insert(0, {
    "role": "system",
    "content": _CHATROOM_OVERRIDE_PROMPT,
})
```

新增模块常量（放 `chatroom_orchestrator.py` 顶部 imports 之后，约 60 行附近）：

```python
_CHATROOM_OVERRIDE_PROMPT = (
    "【聊天室协作模式】\n"
    "你正在多 Agent 群聊里发言，不是在跑工作流任务。请遵守以下规则，"
    "它们覆盖你原始 system prompt 中的输出契约：\n"
    "- 用普通自然语言回复，markdown 自由用。\n"
    "- 不要输出纯 JSON、不要包结构化字段（除非另一成员明确要求结构化结果）。\n"
    "- 想接力就用 `@成员名`；不想接力就别 @。\n"
    "- 保持简洁，一两段话足够，避免长篇大论。"
)
```

**为什么 system 块要插在最前**：LLM 通常对 messages 列表末尾的指令更敏感，但
`build_room_context` 已经在第 0 位放了房间主题/目标/任务说明，把覆盖块插在最前
确保 Agent 看到的"两个 system"先后顺序为：

```
[0] 聊天室协作模式（覆盖输出契约）
[1] 房间主题 + 目标 + 任务说明（来自 build_room_context）
[2..] 历史
```

OpenAI / Anthropic 客户端都会把多个 system 拼接或分离处理，行为一致。

### 2.3 影响范围

**改动文件**：
- `backend/src/core/chatroom_orchestrator.py` — 新增常量 + payload 改两行 + insert 一行

**不改**：
- `config/agents.yaml`（保护工作流路径）
- `core/chatroom.py:build_room_context`（保持纯函数，覆盖逻辑放 orchestrator
  里更显式）

**潜在副作用**：
- planner 在群聊里被 @ 时不再吐 host_directive 的 JSON。**这与 A5 矛盾**：
  当前 host_directive 协议靠 LLM 主动包 ```json {actions:[...]} ```` 围栏，
  现在系统级地禁止纯 JSON。**解法**：覆盖 prompt 里加一句"如果需要按主持人协议
  调度成员，请仍按 JSON 围栏给指令"——见下面的备注。
- 工作流路径（Agent Run / ChatPanel）零影响：不走 orchestrator。

**与 A5 host_directive 共存的覆盖 prompt 微调**（已写入上方常量草稿，二次确认）：

补充末尾一行：
```
- 例外：你若是该房间主持人（auto_host），按已有 host_directive 协议在末尾给 JSON 代码块。
```

### 2.4 测试

**单元测试**（同文件新增 case）：

1. `test_run_speaking_task_overrides_output_format_to_text`：
   spy capability，断言 payload 含 `output_format == "text"`。
2. `test_run_speaking_task_inserts_chatroom_override_system`：
   spy capability，读 `messages[0].role == "system"` 且 content 含
   "聊天室协作模式"；`messages[1].content` 含 "[房间主题]"（保留原有
   build_room_context 块）。

**手工验证**：
1. 创建房间，成员含 reviewer，goal/topic 都设为闲聊。
2. 用户发"@reviewer 你今天心情如何"。
3. 断言回复是普通中文段落，**不含** `{"approved":` `"issues":` `severity` 字段。
4. 对照测试：通过 `POST /api/agents/reviewer/invoke {data:{code:"def x(): pass"}}`
   走 ChatPanel 路径，断言回复仍是 JSON 契约（验证 yaml 没动）。

---

## 3. A5：本期不修

A5 涉及 host_directive 协议产出的 `{"actions":[...]}` JSON 文本暴露在房间消息流里，
即使解析成功也会污染聊天界面。

**本 spec 不实现 A5**。等下一份 spec（**Spec 2**）的 A13 用一个新工具
`chatroom_dispatch` 替换整套基于文本的 host_directive 协议——届时主持人不再"输出
JSON 给系统再正则解析"，而是直接调工具，文本部分纯自然语言展示，工具调用结果
不进消息正文。

涉及但不动的代码：

- `chatroom_orchestrator.py:838-933` — `_parse_host_directive` / `_extract_json_object`
- `routes/chatrooms.py:182-207` — auto_host 注入的 host_prompt 文本

**本期注意**：A2 覆盖 prompt 中保留 host_directive 例外条款（见 §2.3 备注），
确保 auto_host 主持人在协议被替换前仍能正常工作。

---

## 4. A6：LLM 重试增强

### 4.1 现状

`openai_client._create_with_compat_retry`（`openai_client.py:327-337`）名字误导：

```python
async def _create_with_compat_retry(self, kwargs: Dict[str, Any]) -> Any:
    """Create a completion, retrying legacy token names for compatible gateways."""
    try:
        return await self.client.chat.completions.create(**kwargs)
    except Exception:
        if "max_completion_tokens" not in kwargs or "max_tokens" in kwargs:
            raise
        fallback = dict(kwargs)
        fallback["max_tokens"] = fallback.pop("max_completion_tokens")
        return await self.client.chat.completions.create(**fallback)
```

只处理 `max_completion_tokens → max_tokens` 这一个 schema 兼容性回退；
其他 503 / 网络抖动 / RateLimitError / APITimeoutError 全部直接 raise，调用方看到
就是失败。

`anthropic_client.chat`（`anthropic_client.py:101-105`）连这个回退也没有，直接 await。
`chat_stream` 的"流式失败回退非流式"路径（`anthropic_client.py:263-277`）只是把
streaming → non-streaming，并不重试。

### 4.2 修法

**(a) 配置（`config/system.yaml` 顶部 `llm:` 段下新增）**

```yaml
llm:
  # 已有字段...
  max_retries: 3                # 总重试次数（不含首发）
  retry_initial_delay: 1.0      # 首次退避秒数；之后 ×2 指数+ ±20% jitter
```

**(b) 新增独立装饰器 / helper（建议放新文件 `core/llm/retry.py`）**

```python
"""LLM call retry helper — exponential backoff with jitter.

捕获瞬态错误：APIConnectionError / APITimeoutError / RateLimitError /
5xx APIError。其他错误（4xx 非 429、auth、bad-request）直接 raise，不重试。
"""

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional

# 延迟 import 避免单测时 anthropic / openai 缺失
def _is_retryable(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in ("APIConnectionError", "APITimeoutError", "RateLimitError"):
        return True
    # APIError(status_code=5xx)
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
    delay = initial_delay
    attempt = 0
    while True:
        try:
            return await fn()
        except BaseException as exc:
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            jitter = delay * (0.8 + 0.4 * random.random())  # ±20%
            if on_retry:
                on_retry(attempt + 1, exc, jitter)
            await asyncio.sleep(jitter)
            attempt += 1
            delay *= 2
```

**(c) 接入点**

OpenAI（`openai_client.py`）：

- `chat`（行 75）和 `chat_stream`（行 165、169）的 `_create_with_compat_retry`
  调用都包一层 `call_with_retry(lambda: self._create_with_compat_retry(kwargs), ...)`。
- 注意：**`chat_stream` 已 yield 第一个事件后不再重试**——见 (e)。

Anthropic（`anthropic_client.py`）：

- `chat` 行 102 的 `await self.client.messages.create(**kwargs)` 用
  `call_with_retry` 包。
- `chat_stream` 行 218 的 `await self.client.messages.create(**kwargs)` 同样
  包，但仅限"建立流连接"的那次 await；进入 `async for event in stream:` 之后
  不重试。

**(d) 进度回调 + WS 推送**

`call_with_retry` 的 `on_retry(attempt, exc, sleep_for)` 由调用方注入。
LLM 客户端不应直接依赖 task registry，但 `Agent.run_stream` / `_run_speaking_task`
持有 `task_id`，可以在调 LLM 前注入闭包：

```python
# 在 _run_speaking_task / Agent.run_stream 包 LLM 调用时
def _on_retry(attempt: int, exc: BaseException, sleep_for: float) -> None:
    if task_registry:
        task_registry.set_progress(
            task_id,
            retry_count=attempt,
            activity=f"重试中 ({attempt}/{max_retries})",
        )
    # 同步广播
    asyncio.create_task(_broadcast(room_id, "chatroom_message_retrying", {
        "task_id": task_id, "message_id": message_id,
        "attempt": attempt, "max_retries": max_retries,
        "error_type": type(exc).__name__,
    }))
```

实现细节：LLM 客户端没有 task 上下文，需要把 `on_retry` 通过参数传进去。两条路：

1. **简单做法**（推荐）：给 `BaseLLMClient.chat / chat_stream` 加可选参数
   `on_retry: Callable | None = None`，由调用方（Agent / orchestrator）从
   contextvar 取出 task_id 后传入。
2. **复杂做法**：用 contextvar `current_retry_callback`；过度设计，**不采纳**。

**(e) AgentProgress 加 retry_count**

`core/task/types.py:42-57` 的 `AgentProgress` 新增字段：

```python
retry_count: int = 0
```

`registry.py:218-222` 的"累加键"逻辑里加上 `retry_count`：

```python
if "retry_count" in delta and delta["retry_count"] is not None:
    progress.retry_count = int(delta["retry_count"])  # 覆盖（最新尝试号）
```

注意是**覆盖**不是累加——progress.retry_count = 当前正在重试的尝试序号，
而不是历史累计。重试成功后由 LLM 调用方在下一次 set_progress 中显式置 0。

**(f) 流式中途断开不重试**

如 (c) 所述：`chat_stream` 只在"建立 stream 连接"那次 await 重试。
`async for event in stream:` 中途网络断开 → 直接 raise 给上层，由 Agent loop
决定如何收尾（写 transcript "error"、消息标 failed）。
这避免"重试一次重新出 token，前端看到重复输出"。

**(g) 失败后 raise 路径不变**

`call_with_retry` 在 `attempt >= max_retries` 时 raise 原异常；现有调用栈
（`Agent.run_stream` 的 except / `_run_speaking_task` 的 except Exception）
按原逻辑标 failed。

### 4.3 影响范围

**改动文件**：
- `backend/src/core/llm/retry.py`（新建，~50 行）
- `backend/src/core/llm/openai_client.py`（包 2 处）
- `backend/src/core/llm/anthropic_client.py`（包 2 处）
- `backend/src/core/llm/base.py`（`chat` / `chat_stream` 签名加 `on_retry`）
- `backend/src/core/task/types.py`（AgentProgress 加字段）
- `backend/src/core/task/registry.py`（set_progress 处理 retry_count）
- `config/system.yaml`（两个新配置项）
- `backend/src/core/chatroom_orchestrator.py`（注入 `on_retry` 闭包）
- `backend/src/api/routes/tasks.py`（Agent Run 路径同样注入）
- 前端 TaskPanel / ChatroomPanel（读 progress.retry_count 渲染"重试中 (N/M)"）

**潜在副作用**：
- 真服务 503 时延迟增大（最坏 1+2+4=7s + jitter）。可接受，因为之前是直接失败。
- 第三方 OpenAI 兼容代理可能把瞬态错误包装成 4xx——`_is_retryable` 只看
  status_code 5xx 和异常类型名，4xx 不重试，符合预期。
- `BaseLLMClient` 子类如果自定义实现了 chat 但没接 `on_retry` 参数：用 `**kwargs` 兜底
  或保持向后兼容（kwarg-only + 默认 None）。

### 4.4 测试

**单元测试**（`backend/tests/unit/test_llm_retry.py` 新建）：

1. `test_call_with_retry_returns_on_first_success`：fn 立即返回，0 次 sleep。
2. `test_call_with_retry_retries_on_connection_error`：前两次抛
   `APIConnectionError`，第三次成功；断言 `on_retry` 被调 2 次，最终返回值正确。
3. `test_call_with_retry_does_not_retry_on_4xx`：抛 `APIError(status_code=400)`，
   立即 raise，不调 on_retry。
4. `test_call_with_retry_exhausts_and_raises`：fn 一直抛 `RateLimitError`，
   max_retries=3 时 on_retry 调 3 次最后 raise 原异常。
5. `test_jitter_within_20_percent`：mock random.random，断言 sleep 区间在
   `[delay*0.8, delay*1.2]`。

**集成测试**（`backend/tests/integration/test_llm_client_retry.py` 新建）：

1. monkeypatch `client.chat.completions.create` 头两次抛 `APIConnectionError`，
   第三次返回 mock response；调 `OpenAIClient.chat(messages)`，断言成功。
2. anthropic 同模式。
3. `test_chat_stream_does_not_retry_mid_stream`：第一个 chunk 后抛 ConnectionError，
   断言 `chat_stream` 直接 raise，不重试。

**手工验证**：
1. 后端启 demo，把 `config.yaml` 的 `base_url` 改到一个 502 的伪端点。
2. 前端发任意消息，观察日志：
   - 第一次失败 + 第二次失败 + 第三次失败的间隔约 1s / 2s / 4s（含 jitter）。
   - 前端 TaskPanel 卡片上"重试中 (1/3) → (2/3) → 失败"依次显示。
3. 复原 base_url，前端发同样消息，正常返回，progress.retry_count 应被重置为 0
   或保持上一次重试号（取实现）——任一行为都接受，主要看不卡死。

---

## 5. 实施顺序与依赖

| 序号 | 任务 | 依赖 | 可并行 |
|------|------|------|--------|
| 1 | A1 聊天室记忆补齐 | 无 | 与 A6 并行 |
| 2 | A6 LLM 重试增强 | 无 | 与 A1 并行 |
| 3 | A2 强制覆盖输出格式 | 无 | 单独做（不改 yaml/agent runtime） |
| 4 | A5 host_directive | **不在本 spec** | 等 Spec 2 |

**建议节奏**：

- A1 / A6 同一份 PR 也行（两块代码不重叠：A1 改 orchestrator + chatroom，
  A6 改 llm/* + task/types + system.yaml），但分开 PR 更易 review。
- A2 单独一个小 PR（只改 orchestrator 一处常量 + payload），改动量最小。
- 三个 PR 都合并后整体跑：
  - `python3 -m pytest backend/tests/ -q`
  - 手工流程：建房间 → 闲聊 → @reviewer 验证 A2 → 第二次同房间问历史验证 A1
    → 把 base_url 改坏验证 A6。

**回归保护**：
- A1 不能影响 ChatPanel / Agent Run 的 reflection 调用。
- A2 不能让 ChatPanel/Agent Run 走的 reviewer 失去 JSON 契约（必须只在
  orchestrator 注入）。
- A6 不能让流式调用产生重复输出（中途断开不重试）。
