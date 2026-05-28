# 聊天室协作机制重构设计 — 2026-05-28

> 重构聊天室的多 Agent 协作机制：goal 工具补全、并行调度普惠、用工具替代文本协议、上下文重叙、运行时提醒注入、自管 todo。
>
> **设计哲学**：不畏缩 + 默认放开 + 能力齐全。灵感来自 Claude Code：tool description 即 prompt、错误是教学、Investigation before action、Identity 短而 behavior examples 详细。

---

## 1. 设计哲学

### 1.1 当前哲学的问题

聊天室目前最大的问题不在某个 bug，而在**协作语言贫瘠**：

- Host 调度靠**文本里塞 JSON**（容易暴露给用户，无 schema 校验）
- 任何 Agent 想多人并发只能依赖 host，自己不能 dispatch
- 上下文拼装把所有 Agent 都用 `role=assistant`，LM 角色错位
- 每条消息只有 `[sender]:` 前缀，runtime 状态变化（goal 改了 / 你被 @ 了）只能塞 system prompt 主体（cache miss）
- 没有自管"todo"的能力，host 拆任务全靠瞎记
- `dispatch_agent` 跟 `chatroom_dispatch`（不存在）混淆

这些问题的共性是：**该用 tool 表达的协作动作没有 tool**，逼 LM 在文本里编码。

### 1.2 借鉴 Claude Code 的设计范式

CC 在多 agent 协作问题上的关键决策：

1. **Tool description 即 prompt**：每个 tool 的描述写得像跟另一个智能体对话，告诉它"什么时候用 / 为什么用 / 不要怎么用"。LM 自然学会调度策略。
2. **错误是教学**：tool 调用失败不是 raise，是把 error 文本塞回 user 消息让 LM 自己看自己学。
3. **不预测，等待**：runtime 不主动猜 LM 要什么，只在 LM 真的请求时才返回上下文。
4. **Identity 短，behavior 详细**：身份一句话，行为示例展开（`✅ 这样` / `❌ 不要这样`）。
5. **运行时状态变化用 `<system-reminder>` 块单独注入**，不污染稳定的 system prompt（cache 友好）。

本 spec 把上述范式系统性应用到聊天室。

---

## 2. 当前痛点（事实层）

### 2.1 文件锚点

| 文件 | 行号 | 问题 |
|------|---|---|
| `backend/src/api/routes/chatrooms.py` | 184-198 | 注入 prompt 让 host 输出 `{"actions":[...]}` 文本协议 |
| `backend/src/core/chatroom_orchestrator.py` | 747-777 | `_parse_host_directive` 解析文本中的 JSON 派发 |
| `backend/src/core/chatroom_orchestrator.py` | 838-878 | `_parse_host_directive` 实现，没做错就 silent fail |
| `backend/src/core/chatroom.py` | 573-605 | `_format_history_message`：所有 agent 都 role=assistant，目标 Agent 看不出"别人说的话" |
| `backend/src/core/chatroom.py` | 608-673 | `build_room_context`：system 块拼接成单段文本，无结构化 |
| `backend/src/capabilities/tools/dispatch_agent.py` | 120 | `max_depth=1`，子 Agent 不能再派 |
| `backend/src/capabilities/tools/chatroom_set_goal.py` | 全文 | 只有覆盖式 set，缺 get / 增量 update |

### 2.2 Agent 体感

> 用户实测：「auto_host@reviewer 是啥功能？」 → reviewer 出 JSON 评审报告 → planer 接 `{"actions":[...]}` JSON 接力 → 用户："为啥你的输出是 json 啊？"

根因：
- reviewer 的本体 prompt 要求"严格输出纯 JSON"（用于工作流场景）→ 闲聊场景没覆盖
- planer 是 host_agent，被注入的 host_directive prompt 强制每次追加 JSON
- 上下文里看不出"用户在闲聊不在派工"

---

## 3. A9 — Goal 工具补全

### 3.1 现状

`backend/src/capabilities/tools/chatroom_set_goal.py` 提供 `chatroom_set_goal(goal, reason)`：覆盖式写入，旧 goal 入 history。

**缺**：
- 读取：Agent 想看当前 goal/topic/summary 时只能依赖 system prompt 里的快照（已被覆盖前缀挤压）
- 增量更新：很多场景是"在原 goal 基础上加子目标 / 标记已完成 / 修订"，覆盖式不合适

### 3.2 新工具设计

#### `chatroom_get_goal`

```python
class ChatroomGetGoalCapability(CapabilityBase):
    """读取当前房间的目标和元状态（topic/goal/summary/members）。
    
    什么时候用：
      - 你刚被叫进房间，想知道这房间在干嘛
      - 房间已经聊了一段时间，goal 可能变过，你不确定
      - 决定"该不该插话/派人"前先看一眼 goal
    
    返回什么：
      - topic: 房间主题（不变）
      - goal: 当前主目标
      - goal_revisions: 历史改动次数
      - summary: 房间已总结的过往
      - members: 当前成员列表（含动态成员）
      - your_role: 你在这房间叫什么名字
    """
    
    name = "chatroom_get_goal"
    parameters = {}  # 无参数
    
    async def execute(self) -> Dict[str, Any]:
        room_id = get_current_room_id()  # 来自 contextvar
        room = ChatroomStore.get_room(room_id)
        return {
            "topic": room.get("topic"),
            "goal": room.get("goal"),
            "goal_revisions": len(room.get("goal_history") or []),
            "summary": room.get("summary"),
            "members": [...],
            "your_role": get_current_speaker_name(),
        }
```

#### `chatroom_update_goal`

```python
class ChatroomUpdateGoalCapability(CapabilityBase):
    """增量更新房间目标 — 在原 goal 上加子目标 / 标记完成 / 修订。
    不像 chatroom_set_goal 那样整段覆盖。
    
    什么时候用：
      - 把"做完一份评审报告"加到现有目标
      - 标记"已完成代码生成"子目标
      - 微调措辞
    
    什么时候 *不* 用：
      - goal 整体方向变了 → 用 chatroom_set_goal
      - 只是想问 goal 是什么 → 用 chatroom_get_goal
    """
    
    name = "chatroom_update_goal"
    parameters = {
        "operation": {"type": "string", "enum": ["add_subgoal", "mark_done", "revise", "remove_subgoal"]},
        "content": {"type": "string", "description": "操作内容；revise 时传完整新文本，其他时传子目标文本"},
        "subgoal_id": {"type": "string", "description": "对已有子目标操作时必填", "required": False},
        "reason": {"type": "string", "required": False},
    }
```

数据模型：goal 内部用 markdown 表达子目标列表，update 操作只是结构化的 patch。详见 §11。

### 3.3 实施
- 新建 `backend/src/capabilities/tools/chatroom_get_goal.py`
- 新建 `backend/src/capabilities/tools/chatroom_update_goal.py`
- 自动注册给所有 Agent，房间外调用直接 error（沿用 `chatroom_set_goal` 的 contextvar 检查）

### 3.4 测试
- `test_chatroom_get_goal_returns_current_state`：set goal → get → 字段一致
- `test_chatroom_update_goal_add_subgoal_appends`：原 goal "X" → add "Y" → goal 含 X 和 Y
- `test_chatroom_update_goal_mark_done_keeps_history`：mark_done 后 goal_history 包含原条目
- `test_chatroom_get_goal_outside_room_errors`：在 chatroom 外调用返回 `permission_denied`

---

## 4. A12 — 真正的并行调度（提示词层）

### 4.1 事实核查

代码层面**已经支持并行**：

```python
# chatroom_orchestrator.py:762-769
for action in directive_actions:
    dispatch_speaking_task(  # 内部 asyncio.create_task，立刻返回
        room_id,
        action["agent"],
        ...
    )
```

`for + dispatch_speaking_task` 是同步循环，每个 dispatch 内部 `create_task`，**多个 agent 在 event loop 里真的并行 stream**。

### 4.2 真问题

planer 提示词每次只输出 1 个 action（`routes/chatrooms.py:184-198` 的 host_directive 注入只示例了单 action 的格式），所以并行能力空转。

### 4.3 修法

在 A14 协作覆盖前缀和 A13 `chatroom_dispatch` 工具描述里，**用示例式**鼓励多 action：

```
✅ 你想让 reviewer 评一下 + coder 改一下
   → 一次调 chatroom_dispatch([{agent:"reviewer", prompt:"..."}, {agent:"coder", prompt:"..."}])
   → 两人同时开始工作

❌ 先派 reviewer，等他说完再决定要不要派 coder
   → 浪费时间，把并行变串行
```

LM 看 examples 远比看抽象描述有用（CC 范式 #4：Identity 短，behavior 详细）。

### 4.4 测试
- `test_chatroom_dispatch_multiple_actions_run_concurrently`：dispatch 3 个 agent → 3 个 speaking task 同时 RUNNING
- `test_chatroom_dispatch_no_serial_blocking`：第 1 个 agent 慢 5s，第 2 个 agent 1s 内就开始 stream（不等第 1 个）

---

## 5. A13 — `chatroom_dispatch` 工具替代 `{"actions":[...]}` 文本协议

### 5.1 现状

`routes/chatrooms.py:184-198`：

```python
if bool(settings.get("auto_host")):
    if host_in_members:
        # 给 host 注入一段提示，鼓励它输出结构化 host_directive JSON
        prompt += (
            '...\n请在你的回复末尾追加一段 JSON：\n'
            '{"actions": [{"agent": "成员名", "prompt": "..."}]}\n'
            ...
        )
```

`chatroom_orchestrator._parse_host_directive`（`:838-878`）解析消息正文中的 JSON。

### 5.2 问题
- JSON 暴露给用户（A5 bug）
- 只有 host_agent 能用
- 解析失败 silent fail
- LM 容易把"调度指令"和"对话内容"混在一段文本里出，进退两难

### 5.3 新工具

```python
class ChatroomDispatchCapability(CapabilityBase):
    """让多个 Agent 并行加入房间发言。任何成员都能调，不只是 host。
    
    什么时候用（关键）：
      - 想让多个 Agent 干不同的事 → 一次列多个 actions（这是默认！）
      - 看到事情自己能解决就直接派 → 不需要请示别人
      - @<name> 是简化形式：单 action 派单人
    
    什么时候 *不* 用：
      - 你只是想说话，没要派别人 → 直接说，不要调这个工具
      - 想私下让子 Agent 算东西（不公开）→ 用 dispatch_agent（如果开了的话）
    
    返回什么：
      - dispatched: [{task_id, agent_name, status: "dispatched"}]
      - 不阻塞，被派的 Agent 会陆续在房间里发言
    """
    
    name = "chatroom_dispatch"
    parameters = {
        "actions": {
            "type": "array",
            "description": "要派发的 Agent 列表。一次列多个能并行，列单个等同 @mention",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "目标 Agent 名"},
                    "prompt": {"type": "string", "description": "给该 Agent 的具体指令（可选）"},
                },
                "required": ["agent"],
            },
        },
    }
```

实现要点：
- 落到 `backend/src/capabilities/tools/chatroom_dispatch.py`
- 用 contextvar 取当前 `room_id` / `parent_message_id` / `speaker_name`
- 内部直接调 `chatroom_orchestrator.dispatch_speaking_task` 多次（不阻塞）
- 返回 `{dispatched: [...], message: "已派发 N 个 Agent，他们的发言会陆续在房间里出现"}`
- 错失败的 agent 名（不在 members 里）直接在返回值里报，让 LM 自己读自己改（CC 范式 #2 错误是教学）

### 5.4 删除文本协议

A13 实施完后**删除以下代码**：
- `routes/chatrooms.py:184-198` host_directive prompt 注入逻辑
- `chatroom_orchestrator.py:838-878 _parse_host_directive` 函数
- `chatroom_orchestrator.py:747-769` 调用 `_parse_host_directive` 的整段
- 仅保留：mention 接力（`elif mentions:` 那段，因为用户 / Agent @ 还是要 work）
- A2 的"不输出裸 JSON"覆盖前缀里的"主持人例外"条款也一并删掉（Spec 1 已预告）

A5（host_directive 文本暴露）随之自动消失。

### 5.5 auto_host 的角色变化

不再是"专属 host 才能调度"，退化为：
- **默认行为**：用户发消息没 @ 任何人 → 自动让 `settings.host_agent` 接话
- 接话后 host 可以调 `chatroom_dispatch`（跟普通 Agent 一样）
- 任意 Agent 都能调 `chatroom_dispatch`（不限 host）

### 5.6 测试
- `test_chatroom_dispatch_single_agent_replaces_mention`：dispatch([{agent:"reviewer"}]) → reviewer 被派发 speaking task
- `test_chatroom_dispatch_multiple_agents_parallel`：dispatch([reviewer, coder]) → 2 个 speaking task 同时启动
- `test_chatroom_dispatch_unknown_agent_returns_error`：派给不存在的 agent → 返回里 `failed: [{agent, reason}]`
- `test_chatroom_dispatch_outside_room_errors`：在 chatroom 外调用 → permission_denied
- `test_legacy_host_directive_parser_removed`：grep 项目代码 `_parse_host_directive` 应不存在
- `test_user_message_no_visible_json_after_dispatch`：host 派发后房间消息正文不含 `{"actions":...}`

---

## 6. A14 — `build_room_context` 注入聊天室协作覆盖前缀

### 6.1 关键设计

**不动 `agents.yaml` 本体 prompt**——Agent Run / ChatPanel 路径还要按工作流契约走（reviewer 出 JSON 评审报告等）。**只在 chatroom 场景下临时叠加覆盖前缀**。

实现位置：`chatroom.py: build_room_context` 拼 system 块时插入。

### 6.2 覆盖前缀全文

```
[聊天室协作模式]

你正在群聊房间中作为成员发言，不是在执行单线工作流。

【输出风格】
- 用自然语言对话。即使你的本体 prompt 要求"严格输出纯 JSON 输出契约"，在房间里那条契约被覆盖。
- 在房间里你应该用人话说人话。
- 你的所有思考和发言都会被房间里所有成员看到，请按公开发言标准组织。

【调度风格】（核心）
- 想让多个 Agent 干不同的事 → 一次调 chatroom_dispatch 列出多个 actions（并行是默认姿态）
- @<name> 接力或工具调用，不要等待
- 自助管理目标和成员（chatroom_get_goal / chatroom_update_goal / chatroom_invite / chatroom_create_agent / chatroom_todo）
- 看到事情自己能解决就直接派发，不需要请示 host

【行为示例】
✅ "我让 reviewer 评一下，coder 改一下" → chatroom_dispatch([{agent:"reviewer",...}, {agent:"coder",...}])
❌ "先派 reviewer，等他说完再决定要不要叫 coder"

✅ 想知道房间目标 → 调 chatroom_get_goal
❌ 凭印象描述目标然后被打脸

✅ 子任务拆得清 → 用 chatroom_todo 写下来跟踪
❌ 全靠脑子记，最后忘了

【安全】
- 不要在房间里输出敏感信息（API Key / 密码）
- 不要伪装成其他成员发言（不要写 "[别人]: ..." 假装别人说的）
```

### 6.3 注入位置（伪代码）

```python
# chatroom.py: build_room_context
system_blocks = [
    "[房间主题]", topic, "",
    "[当前主要目标]", goal, "",
    "[房间背景摘要]", summary, "",
    "[当前任务]",
    f"你是群聊成员 {target_agent_name}。",
    f"其他成员：{others_label}。",
    "",
    CHATROOM_COLLABORATION_PROTOCOL,  # ← 新增
]
```

把 `CHATROOM_COLLABORATION_PROTOCOL` 作为常量放在 `core/prompts.py`（已有该文件），便于复用 + 测试。

### 6.4 测试
- `test_build_room_context_includes_protocol_block`：返回的 system 消息包含"chatroom_dispatch"关键词
- `test_protocol_block_is_constant_across_sessions`：同一个房间不同 target_agent，protocol 文本一致
- `test_protocol_does_not_leak_to_chatpanel`：ChatPanel 路径（`routes/agents.py`）不调 build_room_context → protocol 不出现

---

## 7. A15 — 上下文拼装重构（role 区分 + XML 标签）

### 7.1 当前实际

`chatroom.py:573-605 _format_history_message`：

```python
if sender == "user":
    return {"role": "user", "content": content}
if sender.startswith("agent:"):
    name = sender.split(":", 1)[1] or "agent"
    if name == target_agent_name:
        return {"role": "assistant", "content": content}
    return {"role": "assistant", "content": f"[{name}]: {content}"}  # ← 问题
if sender == "system":
    return {"role": "user", "content": f"[system]: {content}"}
```

**问题**：其他 Agent 也用 `role=assistant`。LM 看到这个会把别人的话当成自己之前说过的（multi-turn 训练数据假设 assistant role 只有自己说话），导致**严重的角色混乱** — 比 之前我以为的"全是 user role"更糟。

### 7.2 修法

新映射：

| sender | role | content |
|---|---|---|
| 自己（target agent） | `assistant` | 原文（无前缀，是自己以前说的） |
| 用户 | `user` | `<msg id=".." from="user" at=".." mentions="..">原文</msg>` |
| 别的 Agent | `user` | `<msg id=".." from="<agent>" at=".." mentions=".." parent="..">原文</msg>` |
| 系统消息 | `user` | `<system_event at="..">原文</system_event>` |
| 占位/streaming/failed | 跳过 | — |

要点：
- **只有自己用 assistant role**，让 LM 清晰知道"哪些是我说过的"
- 别人的话用 XML 标签包裹元数据（id/from/at/mentions/parent_id），LM 能看出对话 thread 关系
- system 消息不再混入第一条 user role 而是独立块

### 7.3 实现

```python
def _format_history_message(message, target_agent_name) -> Optional[Dict[str, str]]:
    if message.get("status") != "done":
        return None
    
    sender = str(message.get("sender") or "")
    content = str(message.get("content") or "")
    if not content.strip():
        return None
    
    msg_id = message.get("id", "")
    sent_at = message.get("created_at", "")
    mentions = message.get("mentions") or []
    parent = message.get("parent_message_id") or ""
    
    if sender == f"agent:{target_agent_name}":
        return {"role": "assistant", "content": content}
    
    if sender == "user":
        attrs = [f'id="{msg_id}"', 'from="user"', f'at="{sent_at}"']
        if mentions:
            attrs.append(f'mentions="{",".join(mentions)}"')
        return {
            "role": "user",
            "content": f"<msg {' '.join(attrs)}>{content}</msg>",
        }
    
    if sender.startswith("agent:"):
        name = sender.split(":", 1)[1]
        attrs = [f'id="{msg_id}"', f'from="{name}"', f'at="{sent_at}"']
        if mentions:
            attrs.append(f'mentions="{",".join(mentions)}"')
        if parent:
            attrs.append(f'parent="{parent}"')
        return {
            "role": "user",
            "content": f"<msg {' '.join(attrs)}>{content}</msg>",
        }
    
    if sender == "system":
        return {
            "role": "user",
            "content": f'<system_event at="{sent_at}">{content}</system_event>',
        }
    
    return {"role": "user", "content": f'<unknown_msg from="{sender}">{content}</unknown_msg>'}
```

### 7.4 system 块同步重构

把 §6.3 的拼接改成 XML 化（CC 范式 #5：稳定块和浮动块分离便于 cache）：

```xml
<chatroom_context>
  <topic>{topic}</topic>
  <goal current="...">{goal}</goal>
  <summary>{summary}</summary>
  <members self="{target_agent_name}">{members_csv}</members>
  <protocol>
    {CHATROOM_COLLABORATION_PROTOCOL}
  </protocol>
</chatroom_context>
```

LM 拿到的 system message 是结构化的，跟 history XML 标签呼应。

### 7.5 测试
- `test_format_history_self_agent_uses_assistant_role`：sender=agent:reviewer, target=reviewer → role=assistant
- `test_format_history_other_agent_uses_user_role_with_xml`：sender=agent:reviewer, target=coder → role=user, content 含 `<msg from="reviewer"`
- `test_format_history_user_message_xml_includes_mentions`：用户消息含 `@coder` → content 里有 `mentions="coder"`
- `test_format_history_skips_pending_streaming_failed`：status != done 的消息不出现
- `test_build_room_context_system_block_is_xml`：system message 含 `<chatroom_context>` 根标签
- 集成：`test_agent_can_reference_other_agent_message_id`：让一个 Agent 调 chatroom_dispatch 时引用某条 msg id → 工具调用参数里 prompt 包含该 id（说明 LM 真的"看到"了 XML 标签）

---

## 8. A16 — system-reminder 风格运行时上下文注入

### 8.1 设计

灵感来源 Claude Code 的 `<system-reminder>` 块：runtime 在每次 LM 调用时主动注入"鲜活的"运行时变化，**不放进 system prompt 主体（cache 友好）**，而是单独 user 消息块在 history 末尾。

格式：

```xml
<system-reminder>
  你刚被 @ 了。最近一条用户消息是 m_xxx。
  房间 goal 在你上次发言后被 reviewer 改过一次，现在是："{new_goal}"
  当前在房间里活跃成员：reviewer (streaming), coder (idle)
</system-reminder>
```

### 8.2 触发场景

- **goal 变化**：上次该 Agent 发言到现在，goal 被改过 → 提醒它去看新 goal
- **新成员**：上次到现在新加入了 Agent → 提醒它考虑要不要协作
- **被 @**：明确告知"你被 @ 了，期待你接话"
- **工具调用违规警告**：上次调用 chatroom_dispatch 派给了不存在的 Agent → 这次提醒它去 chatroom_get_goal 看成员

### 8.3 实现位置

`chatroom_orchestrator._run_speaking_task` 拼 payload 时：

```python
context_messages = build_room_context(room_snapshot, agent_name)

reminders = build_system_reminders(  # 新函数
    room=room_snapshot,
    target_agent=agent_name,
    parent_message_id=parent_message_id,
)
if reminders:
    context_messages.append({
        "role": "user",
        "content": f"<system-reminder>\n{reminders}\n</system-reminder>",
    })
```

`build_system_reminders` 函数检查房间状态变化，生成简短的"鲜活提醒"。**短就是力**——超过 3 条就截断，避免 LM 注意力被稀释。

### 8.4 测试
- `test_system_reminder_includes_goal_change`：上次发言到现在 goal 改过 → reminder 里有 "goal 改过"
- `test_system_reminder_includes_new_members`：有新成员入群 → reminder 提及
- `test_system_reminder_truncates_when_too_many`：触发 5 个 reminder 类型 → 只保留前 3 条
- `test_system_reminder_absent_when_nothing_changed`：第一次发言 / 无变化 → 不注入

### 8.5 WS 事件（调试用）

新增 `chatroom_system_reminder`，前端可在调试模式下看到 runtime 注入了什么 reminder：

```json
{
  "event_type": "chatroom_system_reminder",
  "data": {
    "room_id": "...",
    "task_id": "...",
    "agent_name": "...",
    "reminders": ["goal changed", "new member: design_agent"]
  }
}
```

---

## 9. A17 — `chatroom_todo` 工具（host 自管计划）

### 9.1 设计

灵感来自 Claude Code 的 `TodoWrite`：让 LM **自己写计划、自己更新进度**，runtime 不强求外部 orchestrator 决策。

### 9.2 数据模型

```python
@dataclass
class ChatroomTodo:
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "blocked"]
    assignee: Optional[str]   # agent_name 或 "user"
    created_at: datetime
    updated_at: datetime
    parent_dispatch_id: Optional[str]  # 关联的 chatroom_dispatch task_id
    notes: Optional[str]
```

存储：`Chatroom.todos: list[ChatroomTodo]`（写入 `data/chatrooms/{room_id}.json`）

### 9.3 工具

```python
class ChatroomTodoCapability(CapabilityBase):
    """房间内任务清单管理。任意成员都能用。
    
    什么时候用（关键）：
      - 你看到一个事情有多个步骤，先 chatroom_todo create 把所有步骤写下来
      - 你完成了一个子任务 → chatroom_todo complete <id>
      - 看不清现在该干啥 → chatroom_todo list 看清楚
    
    设计哲学：写下来你才不会忘。这跟你脑子里的 plan 不一样，所有人都能看到。
    """
    
    name = "chatroom_todo"
    parameters = {
        "action": {"type": "string", "enum": ["create", "update", "complete", "block", "list", "delete"]},
        "todos": {  # action=create 时
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "assignee": {"type": "string", "required": False},
                },
            },
            "required": False,
        },
        "todo_id": {"type": "string", "required": False},  # update/complete/block/delete 时
        "status": {"type": "string", "required": False},
        "notes": {"type": "string", "required": False},
    }
```

### 9.4 跟 chatroom_dispatch 配合

调 `chatroom_dispatch` 时自动给每个 dispatch action 创建一条 todo（status=pending, assignee=action.agent, parent_dispatch_id=task_id）。该 agent 完成 speaking task 后自动 mark complete。

### 9.5 前端展示

`ChatroomPanel.tsx` 在消息流上方加一个 `<TodoBanner>`，实时展示当前房间 todos（按 status 分组）。WS 事件：
- `chatroom_todo_added` / `chatroom_todo_updated` / `chatroom_todo_completed` / `chatroom_todo_deleted`

### 9.6 测试
- `test_chatroom_todo_create_appends_to_room`：create 3 个 → room.todos 长度 +3
- `test_chatroom_todo_complete_updates_status_and_timestamp`：complete → status=completed, updated_at 变
- `test_dispatch_auto_creates_todos`：chatroom_dispatch 多 actions → 自动产生 N 条 pending todos
- `test_speak_task_done_auto_completes_associated_todo`：被派发的 agent 完成发言 → 关联 todo 自动 complete
- `test_chatroom_todo_list_returns_all`：list → 返回完整列表
- `test_chatroom_todo_outside_room_errors`：room 外调用报错

---

## 10. A20/A21 — 设计权衡

### 10.1 A20：对话 vs 聊天室上下文

| 维度 | ChatPanel/Agent Run | 聊天室 |
|---|---|---|
| 子 Agent 思考是否暴露 | 否（被 dispatch_agent 隐藏在 notification_box） | 是（所有发言公开） |
| 上下文纯净度 | 高 | 低 |
| 用户介入能力 | 弱 | 强（能围观 + 插话） |
| Token 消耗 | 低 | 高 |
| 多 Agent 真协作 | 父子私聊 | 多边公开 |

**这不是 bug，是 trade-off**。A14 协作覆盖前缀里加一句"你的所有思考都会被房间所有成员看到"明确告知 Agent 这一点。

### 10.2 A21：聊天室默认不挂 `dispatch_agent`

理由：
- 聊天室协作哲学是"想让别人干活就 @ 他公开干"，不是"私下派子 Agent"
- 私下派的话用户根本不知道发生了什么（违背聊天室"围观一切"的设计）
- chatroom_dispatch（公开 @）已经覆盖 99% 协作场景

修法：
- `chatroom_orchestrator._run_speaking_task` 拼 payload 时，**从 capability list 移除 `dispatch_agent`**
- 例外：房间 settings 显式 `allow_subagent_dispatch: True` 时保留

测试：
- `test_chatroom_default_blocks_dispatch_agent`：默认配置房间，agent payload tools 列表里无 dispatch_agent
- `test_chatroom_with_allow_subagent_dispatch_includes_it`：开启该配置后 dispatch_agent 出现

---

## 11. 数据模型变更

### 11.1 `Chatroom`

```python
class Chatroom:
    # ... 现有字段
    settings: dict   # 已有，但加 2 个键：
                     #   auto_memory: bool = True       (Spec 1 A1)
                     #   allow_subagent_dispatch: bool = False  (本 spec A21)
    todos: list[ChatroomTodo]  # 新增 (A17)
    goal_subgoals: list[GoalSubgoal]  # 新增 (A9 增量更新)
```

### 11.2 `ChatroomTodo`（已在 §9.2 定义）

### 11.3 `GoalSubgoal`（A9 增量更新支持）

```python
@dataclass
class GoalSubgoal:
    id: str
    content: str
    status: Literal["pending", "done"]
    created_at: datetime
    done_at: Optional[datetime]
```

`chatroom_get_goal` 返回时把 `goal` 字段渲染为 `主目标 + 子目标 markdown 列表`。

### 11.4 持久化

`data/chatrooms/{room_id}.json` 序列化 Chatroom 全字段。`_index.json` 摘要不变。

---

## 12. WebSocket 新事件

| 事件 | 触发时机 | 数据 |
|---|---|---|
| `chatroom_dispatch_called` | A13 chatroom_dispatch tool call 成功 | room_id, dispatcher, dispatched_task_ids, actions |
| `chatroom_todo_added` | A17 create | room_id, todos: [新增列表] |
| `chatroom_todo_updated` | A17 update/block/notes | room_id, todo |
| `chatroom_todo_completed` | A17 complete（人工/自动） | room_id, todo_id, completed_at |
| `chatroom_todo_deleted` | A17 delete | room_id, todo_id |
| `chatroom_goal_subgoal_added` | A9 add_subgoal | room_id, subgoal |
| `chatroom_goal_subgoal_done` | A9 mark_done | room_id, subgoal_id |
| `chatroom_system_reminder` | A16 注入 reminder | room_id, agent_name, reminders（前端调试用） |

前端订阅 `chatroom:<id>` 频道收事件，更新对应 UI 区块。

---

## 13. 实施顺序

按依赖关系：

```
Phase 1 (基础重构，独立)
├── A14 协作覆盖前缀 → core/prompts.py 加常量 + chatroom.py 引用
└── A15 上下文拼装重构 → chatroom.py:_format_history_message 重写
   (这两个可并行)

Phase 2 (新工具，依赖 Phase 1)
├── A9 chatroom_get_goal / chatroom_update_goal
├── A13 chatroom_dispatch（删除 host_directive 文本协议）
└── A17 chatroom_todo
   (这三个可并行，但 A13 删除 host_directive 时同步删 A2 的"主持人例外"条款)

Phase 3 (运行时优化)
├── A16 system-reminder 注入
└── A21 聊天室默认不挂 dispatch_agent

Phase 4 (前端)
├── ChatroomPanel TodoBanner
├── 新 WS 事件订阅与处理
└── 调试模式 system-reminder 可视化（可选）

Phase 5 (文档同步)
└── CLAUDE.md §3.10 更新；docs/superpowers/specs/2026-05-26-agent-chatroom-design.md 加补充章节
```

A12（提示词鼓励多 action）随 A14 / A13 自然完成，不单立 phase。

---

## 14. 测试策略

### 14.1 单元测试覆盖

每个新工具一份 test 文件，至少覆盖：
- 正常路径
- 房间外调用 / 缺参数 / 错误参数
- contextvar 缺失（不在 task 上下文内）

参考现有测试结构：
- `backend/tests/unit/test_chatroom_tools.py`（已有 chatroom_set_goal/invite/create_agent 测试）

### 14.2 集成测试

`backend/tests/integration/test_chatroom_pipeline.py` 已有 chatroom 集成测试套件。在其基础上加：

- `test_e2e_user_message_dispatches_via_tool_not_text`：用户发消息 → host 回复 → 不应在消息正文出现 JSON
- `test_e2e_two_agents_dispatched_in_parallel_complete_in_parallel`：派发 2 agent → 同时 RUNNING → 同时收到 chatroom_message_done
- `test_e2e_other_agent_message_appears_as_user_role_with_xml`：完整对话 → 检查 build_room_context 输出
- `test_e2e_todo_lifecycle_create_through_dispatch_to_complete`：dispatch 自动建 todo → speaking task 完成 → todo 自动 complete

### 14.3 回归测试

- `test_chatpanel_does_not_use_chatroom_protocol`：ChatPanel 路径调 Agent 时 system prompt **不**含 `[聊天室协作模式]` 字串（确保覆盖前缀只在房间生效）
- `test_legacy_host_directive_text_protocol_not_invoked`：grep 项目代码，`_parse_host_directive` 函数应不存在；`/api/chatrooms/{id}/messages` 路由不再注入 host_directive prompt

### 14.4 手工验收

实施完成后手工跑一遍：
1. 创建房间，开 auto_host
2. 用户问"什么是 X"（闲聊）→ host 用自然语言回答，不出现 JSON
3. 用户说"@reviewer 评审一下 + @coder 改一下"→ chatroom_dispatch 同时派 2 人 → 房间同时出现两条 streaming 消息
4. 调 chatroom_get_goal → 返回结构化数据
5. 调 chatroom_update_goal add_subgoal "完成评审" → 前端 banner 子目标列表更新
6. 调 chatroom_todo create → banner 出现 todo 项
7. dispatch 完成后 todo 自动 complete

---

## 15. 风险与回滚

### 15.1 风险

- **删除 `_parse_host_directive` 后某些用户依赖文本 JSON**：通过 release notes 提醒；保留一段时间的"解析到就警告"的兜底（实现层加 deprecation log）
- **XML 标签注入 LM 后某些 LM provider 不喜欢 user role 含标签**：先在 OpenAI / Anthropic / DeepSeek 三个主流 provider 跑通再合并
- **A17 todo 数据膨胀**：单房间 todos > 100 时前端分页 / 后端过期归档（写入 spec 补充章节，不在本期实施）

### 15.2 回滚路径

- 单 commit 单 task，每完成一个 phase 一次集成测试
- 真出问题：Phase 4 前端可独立 revert（不影响后端）
- 后端核心改动（A14/A15）有 feature flag `system.yaml: chatroom.use_xml_context: True`（默认开），关掉就走旧路径

---

**文档完毕。**
