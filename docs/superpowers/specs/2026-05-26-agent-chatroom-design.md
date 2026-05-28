# Agent 聊天室（Chatroom）设计文档

**版本**: v1.0
**日期**: 2026-05-26
**作者**: 项目维护者
**状态**: 待实现

> **2026-05-28 更新**：协作机制重构见 [`2026-05-28-chatroom-collaboration-design.md`](2026-05-28-chatroom-collaboration-design.md)
> （host_directive 文本协议删除，XML 化 system 块 + history，`<system-reminder>` 注入，
> `chatroom_dispatch` / `chatroom_get_goal` / `chatroom_update_goal` / `chatroom_todo` 工具，
> 默认屏蔽 `dispatch_agent`）。本文为 1.0 基线。

> 在现有 1v1 ChatPanel 之外，新增"多 Agent 群聊"模块。
> Agent 之间能通过 `@` 互相接力、自治拉人/造人，房间可绑定工作区，可全自动协作完成任务。
> 与现有 `ChatHistoryStore` / `ChatPanel` 完全独立，不破坏既有功能。

---

## 1. 目标与非目标

### 1.1 目标

- 提供一个"聊天室"形态的多 Agent 协作界面，把现有的 4 个 Agent + 动态 Agent 装进同一个对话流。
- Agent 之间通过 `@` mention 接力发言，形成可观察的多智能体协作过程。
- Agent 可在运行时邀请已有 Agent 入群，或动态创建新 Agent 入群（默认全自动，无需人类批准）。
- 每个房间可绑定一个工作区；房间内所有 Agent 的工作区类工具落到该工作区。
- 每个房间有 `topic`（主题）和 `goal`（当前目标），所有 Agent 发言时都看得到。
- 流式呈现 Agent 思考、工具调用、最终回复，群聊"直播"质感。

### 1.2 非目标

- **不**改造现有 `ChatPanel`，单聊功能保持不动。
- **不**统一 `ChatHistoryStore` 与新存储；二者分开演进。
- **不**做多用户协作（单浏览器一个会话即可，不引入鉴权/权限）。
- **不**做消息编辑/撤回（毕设范围内不必要）。
- **不**做跨房间消息引用/检索（YAGNI）。

---

## 2. 总体架构

### 2.1 与现有系统的关系

```
              ┌─────────────────────────────────────┐
              │   现有：ChatPanel + ChatHistoryStore  │  ← 不动
              └─────────────────────────────────────┘
                                                       
              ┌─────────────────────────────────────┐
新增 ──→     │   ChatroomPanel + ChatroomStore       │
              │                                       │
              │   └─ 复用：AgentRegistry              │
              │   └─ 复用：TaskRegistry / transcript  │
              │   └─ 复用:UnifiedBus / WebSocket    │
              │   └─ 复用：Agent.run_stream           │
              │   └─ 复用：workspace 工具与 ContextVar │
              └─────────────────────────────────────┘
```

### 2.2 核心抽象

**Chatroom** —— 房间。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | UUID |
| `title` | str | 房间名 |
| `topic` | str | 房间主题（静态、长文本） |
| `goal` | str \| None | 当前主要目标（动态、单行） |
| `goal_history` | list | `[{goal, set_by, set_at}]` |
| `members` | list[str] | 静态成员名列表（来自 AgentRegistry） |
| `dynamic_members` | list | `[{name, role_prompt, base_agent}]`，运行时动态创建的 Agent 规格 |
| `workspace_id` | str \| None | 绑定的工作区 id |
| `summary` | str \| None | 早期消息的压缩摘要 |
| `summary_until_msg_id` | str \| None | 摘要覆盖到哪条消息为止 |
| `settings` | dict | 见 §2.3 |
| `created_at` / `updated_at` | str | ISO 时间 |

**ChatroomMessage** —— 房间内一条消息。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | UUID |
| `room_id` | str | |
| `sender` | str | `user` / `agent:<name>` / `system` |
| `content` | str | Markdown 文本 |
| `mentions` | list[str] | 解析出的 `@AgentName` 列表 |
| `parent_message_id` | str \| None | 接力来源 |
| `status` | str | `pending` / `streaming` / `done` / `failed` |
| `task_id` | str \| None | 关联的 speaking task id |
| `meta` | dict | 思考、工具调用日志、token 数等 |
| `created_at` / `updated_at` | str | |

**SpeakingTask** —— 复用现有 `TaskRegistry`，新增枚举值 `TaskType.AGENT_SPEAK`。一次发言 = 一个 task，承载 Agent 思考 / 工具调用 / 最终回复事件，写入 transcript。

### 2.3 房间 settings 字段

| key | 默认 | 说明 |
|---|---|---|
| `auto_host` | False | 用户消息无 mention 时是否调度 host Agent |
| `host_agent` | "planner" | host Agent 名 |
| `recent_n` | 30 | 上下文里保留最近 N 条原文 |
| `summary_threshold_m` | 20 | 距上次摘要 ≥ M 条新消息时触发再摘要 |
| `max_relay_depth` | 3 | Agent 接力链最大深度 |
| `max_members` | 20 | 房间成员上限 |
| `allow_agent_invite` | True | 允许 Agent 调 `chatroom_invite` |

**注**：`allow_agent_create` 不存在——Agent 创建默认开放、不需要人类批准（设计意图：全自动）。

---

## 3. 编排逻辑

### 3.1 用户发消息流程

```
用户消息进房间 (POST /api/chatrooms/{id}/messages)
   │
   ├─ 1. 写入消息（status=done）
   │
   ├─ 2. 解析 @mentions
   │
   ├─ 3a. 有 mention：每个被 @ 的成员各派一个 speaking task
   │
   ├─ 3b. 无 mention 且 auto_host=on：派 host_agent 一个 speaking task
   │      （host 输出 host_directive 系统消息后，再按其 directive 派后续 tasks）
   │
   └─ 3c. 无 mention 且 auto_host=off：什么都不发生
```

### 3.2 Speaking Task 内部流程

```
1. 创建 TaskType.AGENT_SPEAK，立即返回 task_id
2. 房间插占位消息（sender=agent:<name>, status=pending, task_id=<id>）
   ── 广播 chatroom_message_started ──
3. 后台跑 Agent：
   a. build_room_context(room, target_agent) 拼上下文（见 §3.4）
   b. agent.run_stream(...) 执行，事件按 WS 推送：
      - chatroom_agent_thinking（思考增量）
      - chatroom_tool_call（工具调用）
      - chatroom_tool_result（工具返回）
   c. 最终回复写回占位消息：content=<text>, status=done
   ── 广播 chatroom_message_done ──
4. 接力检测：解析最终回复的 @mentions
   - 每个被 @ 的成员派新 speaking task，parent_message_id=本消息
   - 接力深度（沿 parent 链向上数）超过 max_relay_depth：忽略 mention，
     塞 system 消息 "已达接力上限"
```

### 3.3 上下文构造（c：全公开 + 摘要压缩）

`build_room_context(room, target_agent)` 返回一段 system + history 列表：

```
[system]
[房间主题]
{room.topic}

[当前主要目标]
{room.goal or "（未设定，请根据对话推断）"}

[房间背景摘要]
{room.summary or "（暂无摘要）"}

[当前任务]
你是群聊成员 {target_agent.name}。请在该群聊中发言。
其他成员：{members - target_agent}
你可以用 @<name> 来召唤成员接力发言。

[history]
最近 recent_n 条原文消息（user / agent:* / system 都包含）
按时间正序，每条标注 sender 和 mentions
```

**摘要触发**：
- `build_room_context` 检测到"早于最近 recent_n 条的消息总数" - "summary 已覆盖到的消息数" ≥ summary_threshold_m。
- 满足时 `asyncio.create_task` 派一个后台摘要任务（**不阻塞当前发言**）。
- 摘要任务调用 `summarize_room(room, llm_client)`：拼"早于最近 recent_n 条的全部消息" + `CHATROOM_SUMMARY_PROMPT`（写在 `core/prompts.py`）→ LM → 写回 `room.summary` + `room.summary_until_msg_id`。
- 当前发言用旧摘要先发，新摘要下次用。摘要失败静默吞错（log warning）。

### 3.4 主持模式（auto_host）

- 默认 off。开启时无 mention 的用户消息触发 `host_agent` 一个 speaking task。
- host 的系统提示注入"你是这个群的主持人，列出接下来该让哪些成员发言、为什么、按什么顺序"。
- host 不像普通成员那样输出群聊消息，而是输出一个 **host_directive** 结构（JSON），由编排层解析后按其 directive 派发后续 speaking tasks。
- host_directive 同时以 system 消息形式落进房间历史（"主持调度：先 @ planer 制定计划，再 @ coder 起草模块 A"），让其他 Agent 看得到。

### 3.5 取消与失败

| 场景 | 处理 |
|---|---|
| 用户取消 speaking task | 消息 `failed` "已取消"；递归 kill 所有子接力 task（TaskRegistry.kill 已支持递归） |
| Agent LM 报错 | 消息 `failed`；错误信息写 content；房间继续可用；前端有"重试"按钮 |
| @ 不在 members 的 Agent | 占位消息直接 `failed` "成员 X 不在房间里"，不派 task |
| @ 已失效的 dynamic Agent | 同上，提示"成员已失效" |
| 接力深度超限 | 忽略 mention，塞 system 消息 |

---

## 4. Agent 自治能力（新增工具）

3 个内置 Tool，注册在 `core/capability/native.py`，群聊上下文里默认对所有成员开放。

### 4.1 工具定义

| Tool | 入参 | 行为 |
|---|---|---|
| `chatroom_invite` | `agent_name: str` | 把已注册 Agent 拉入当前房间；写 system 消息 "<inviter> 邀请 <agent_name> 加入"；广播 `chatroom_member_added` |
| `chatroom_create_agent` | `name: str, role_prompt: str, base_agent: str = "generic"` | 运行时造新 Agent 注册到 `AgentRegistry`，自动 invite 进当前房间；写 system 消息；广播 `chatroom_member_added` |
| `chatroom_set_goal` | `goal: str, reason?: str` | 更新当前房间 goal；旧 goal 推进 goal_history；写 system 消息 "目标已更新为：...（by <agent>，原因：...）"；广播 `chatroom_goal_updated` |

### 4.2 上下文注入

新增 ContextVar：`current_room_id`（在 `core/task/context.py`，setter 返回 Token，try/finally reset，模式同现有几个）。

派发 speaking task 时通过该 ContextVar 把 room_id 传给 Agent；3 个工具内部从 ContextVar 取 room_id；群聊外调用直接报错。

### 4.3 限制（防失控，不卡审批）

- `chatroom_create_agent`：单次 speaking task 内最多调 2 次（task 级计数器）；新名字与 AgentRegistry / dynamic_members 重名直接 error。
- `chatroom_invite`：成员数超 `max_members` 直接 error；目标 Agent 未注册 error。
- `chatroom_set_goal`：无额外限制（goal 是字符串，可随时改）。

### 4.4 持久化策略

动态 Agent **不写回** `config/agents.yaml`：
- 房间 JSON 存 `dynamic_members: [{name, role_prompt, base_agent}]`。
- 后端启动时，加载所有房间，扫所有 dynamic_members，按 spec 在 `AgentRegistry` 重新构造（如果 base_agent 不存在则 log warning + 跳过）。
- AgentRegistry 加最小封装 `register_dynamic(name, role_prompt, base_agent)`：实例化 base_agent 类 → 用 `prompt_override` 替换系统提示 → 注册。

---

## 5. 工作区绑定

`Chatroom.workspace_id: str | None`。

派发 speaking task 时把 workspace_id 注入 `workspace_root_override` ContextVar（已存在）；Agent 调 `read_file` / `write_file` / `bash` / `file_search` 等工作区工具时落到该工作区目录。

未绑定工作区的房间，工作区类工具调用直接返回 error "该房间未绑定工作区"。

多房间共享一个工作区允许；不引入互斥锁（毕设阶段不必要）。

---

## 6. 后端 API

前缀 `/api/chatrooms`。

### 6.1 REST 端点

| Method | Path | 说明 |
|---|---|---|
| GET | `/` | 列房间摘要（id, title, topic, goal, members, workspace_id, last_message_at） |
| POST | `/` | 创建房间，body: `{title, topic, goal?, members: [], workspace_id?, settings?}` |
| GET | `/{id}` | 房间详情（含全部消息） |
| PUT | `/{id}` | 更新 title/topic/goal/members/workspace_id/settings |
| DELETE | `/{id}` | 递归 kill in-flight tasks → 删 JSON 文件 |
| GET | `/{id}/messages` | 消息列表，支持 `?since=<msg_id>` 增量 |
| POST | `/{id}/messages` | 用户发言，body: `{content}` → 写消息 + 解析 mention + 派 tasks，返回 `{message, dispatched_tasks: [{agent, task_id}]}` |
| POST | `/{id}/invoke` | 手动召唤某 Agent 发言：`{agent_name, prompt?}` → 派 task |
| POST | `/{id}/cancel` | 取消该房间所有 in-flight speaking tasks |

### 6.2 WebSocket 事件

复用现有 `/ws`，订阅频道 `chatroom:{id}`：

| 事件 | 触发 | payload |
|---|---|---|
| `chatroom_message_added` | 用户/system 消息写入 | `{room_id, message}` |
| `chatroom_message_started` | Agent 占位消息插入 | `{room_id, message}` |
| `chatroom_agent_thinking` | 思考流式块 | `{room_id, message_id, delta}` |
| `chatroom_tool_call` | 工具调用 | `{room_id, message_id, tool_name, args}` |
| `chatroom_tool_result` | 工具返回 | `{room_id, message_id, tool_name, result_preview}` |
| `chatroom_message_done` | 发言完成 | `{room_id, message}` |
| `chatroom_message_failed` | 发言失败/取消 | `{room_id, message_id, error}` |
| `chatroom_summary_updated` | 摘要刷新 | `{room_id, summary}` |
| `chatroom_member_added` | invite/create 成功 | `{room_id, member, by}` |
| `chatroom_member_removed` | 成员移除 | `{room_id, member, by}` |
| `chatroom_goal_updated` | goal 变更 | `{room_id, goal, by, reason?}` |

---

## 7. 文件结构

### 7.1 新增后端文件

```
backend/src/
├── core/
│   ├── chatroom.py                  # ChatroomStore + 数据模型 + summarize_room()
│   └── task/context.py              # 加 current_room_id ContextVar
├── api/
│   ├── routes/chatrooms.py          # 路由
│   └── websocket/handlers.py        # 加 chatroom:{id} 频道广播
├── core/capability/native.py        # 加 3 个聊天室 tool
├── core/prompts.py                  # 加 CHATROOM_SUMMARY_PROMPT 与房间 system prompt 模板
└── core/task/types.py               # 加 TaskType.AGENT_SPEAK
```

### 7.2 新增前端文件

```
frontend/src/
├── components/
│   ├── ChatroomPanel.tsx            # 主面板
│   ├── ChatroomPanel.css
│   ├── ChatroomMessage.tsx          # 单条消息组件
│   └── (Sidebar.tsx)                # 加"聊天室"入口
├── api/client.ts                    # 加 chatroom 相关函数
└── types/index.ts                   # 加 Chatroom / ChatroomMessage 类型
```

---

## 8. 前端 UI

### 8.1 三栏布局

```
┌──────────┬────────────────────────────────────┬───────────┐
│ 房间列表  │ 顶部 banner: topic + goal           │ 成员/设置 │
│          ├────────────────────────────────────┤           │
│ + 新房间 │ 消息流（中央，流式滚动）            │ 成员:     │
│          │                                    │  · planer │
│ #毕设组  │ [user] @planer 帮我...             │  · coder  │
│ #算法答辩│ [P planer] [streaming...]          │  · ...    │
│          │   └ 思考折叠区                     │ [+ 添加]  │
│ ...      │   └ 工具调用卡片 x N               │           │
│          │   └ 正文 (Markdown)                │ 设置:     │
│          │                                    │  □ 主持   │
│          │                                    │  N=30 M=20│
│          │                                    │           │
│          │ [输入框] @▾  [发送]                 │ [清空房间]│
└──────────┴────────────────────────────────────┴───────────┘
```

### 8.2 关键交互

- **顶部 banner**：固定显示 topic（一行省略） + goal（一行高亮），点击展开看完整 + goal_history。goal 变化时 banner 闪烁 + 房间消息流插 system 消息。
- **消息卡片**：头像（首字母色块，每个 Agent 一个固定 hash 色） + 名字 + 状态徽标（pending/streaming/done/failed）。
- **思考折叠区**：默认折叠；展开后看到 thinking 流式文本 + tool_call 卡片（工具名 + 参数缩略 + "展开看完整结果"）。
- **正文**：复用现有 ReactMarkdown；`@AgentName` 渲染成高亮 chip。
- **底部 meta**：耗时 / 工具次数 / token 数 / parent message hover 提示"接力自 ..."。
- **failed 态**：红边 + 错误信息 + "重试"按钮（POST /{id}/invoke 重派）。
- **输入框**：`@` 触发 Agent 选择浮窗，多选支持（`@a @b` 并行）。无 mention 时下面提示"未 @ 任何 Agent，将不会触发回复"（auto_host=on 时改为 "将由 host 决定调度"）。
- **右栏成员管理**：列出 members + dynamic_members（动态的标 `[动态]`，hover 显示 role_prompt）；可加/移除/查看；设置项与房间属性可编辑（auto_host、host_agent、recent_n、summary_threshold_m、max_relay_depth、max_members、allow_agent_invite、workspace_id、topic、goal）。
- **WebSocket**：进入房间订阅 `chatroom:{id}`；切换/退出取消订阅；断线重连后拉一次完整消息列表 + 重新订阅。

---

## 9. 错误处理总表

| 场景 | 处理 |
|---|---|
| @ 不在 members 的 Agent | 占位消息 failed "成员 X 不在房间里" |
| @ 已失效 dynamic Agent | 同上 |
| Agent LM 报错 | 消息 failed；前端"重试"按钮 |
| `chatroom_create_agent` 重名 | 工具返回 error，Agent 自行决定下一步 |
| 单 task 内 `create_agent` 超过 2 次 | 第三次起 error |
| 接力深度超 `max_relay_depth` | 忽略 mention，system 消息提示 |
| 成员超 `max_members` | invite/create error |
| 摘要任务报错 | 静默吞错（log warning）；旧摘要继续用 |
| 工作区类工具但房间没绑 workspace | 工具 error |
| WebSocket 断线 | 前端重连后拉完整列表 + 重订阅 |
| 用户取消 speaking task | 消息 failed "已取消"；递归 kill 子任务 |
| 删除房间但有 in-flight task | 先递归 kill → 删 JSON |

**原则**：聊天室不因单 Agent 失败而崩；错误以消息形式呈现在房间里，符合"群聊"语义。

---

## 10. 测试策略

### 10.1 单元测试（pytest）

- `test_chatroom_store.py` — CRUD、消息追加、并发追加、JSON 持久化往返。
- `test_chatroom_mention_parser.py` — 中文/Unicode/`@@` 转义/连续 @/引号内 @。
- `test_chatroom_context_builder.py` — N/M 阈值切换、摘要存在/不存在、topic+goal 注入位置正确。
- `test_chatroom_relay.py` — max_relay_depth 生效；A→B→C→A 循环被截断。
- `test_chatroom_tools.py` — 3 个 tool 在群聊外调用报错；重名/超员/单 task 创建上限等边界。
- `test_chatroom_workspace.py` — workspace_id 注入正确；未绑定时工作区工具报错。

### 10.2 集成测试

- `test_chatroom_pipeline.py` — echo LM mock 跑完整流程：建房间 → 用户 @ planer → planer 回复里 @ coder → coder 发言 → 摘要触发 → 数据落盘正确。
- `test_chatroom_websocket.py` — 模拟 WS 客户端订阅，验证事件序列（started → thinking → tool_call → done）。

### 10.3 前端

- 项目当前前端无单测框架，毕设阶段不引入。
- 用 dev server + mock LM 浏览器跑通：消息卡片渲染、思考折叠、@ 浮窗、成员实时变化、goal banner 闪烁、断线重连。

### 10.4 验收门槛

- 现有 ~605 个测试不退化。
- 新增 ≥ 40 个聊天室相关测试用例，全部通过。
- 手动验收剧本：
  > 建一个绑定毕设工作区的房间 → 让 planer 制定计划 → planer 自己 @coder 并中途 `chatroom_create_agent('docs_writer', ...)` → coder 写代码、docs_writer 写文档 → planer 把 reviewer 拉进来 (`chatroom_invite`) 审 → 整个过程 5 分钟内完成、无后端报错。

---

## 11. 分阶段实施

每阶段独立可演示；老 ChatPanel 始终可用。

### Phase 1 — 后端骨架（约 2 天）

- `core/chatroom.py`：ChatroomStore + 数据模型 + JSON 持久化。
- `api/routes/chatrooms.py`：CRUD + messages + invoke + cancel 全套 REST。
- `core/task/types.py`：加 `TaskType.AGENT_SPEAK`。
- `core/task/context.py`：加 `current_room_id` ContextVar。
- 单元测试：store + mention parser + context builder。
- **里程碑**：curl 建房间、发消息、阻塞模式单 Agent 返回。

### Phase 2 — 编排 + 流式（约 2 天）

- speaking task 调度器（接 `Agent.run_stream`）。
- 接力解析 + max_relay_depth 检查。
- WebSocket 频道 `chatroom:{id}` 接入现有 handlers。
- 摘要任务（`build_room_context` + 异步触发 + `CHATROOM_SUMMARY_PROMPT`）。
- 集成测试：mock LM 跑完整接力链。
- **里程碑**：curl + websocat 看消息流式蹦出。

### Phase 3 — 前端聊天室（约 2 天）

- ChatroomPanel + Sidebar 入口。
- 消息卡片（思考折叠 / 工具展示 / 状态徽标）。
- 输入框 @ 浮窗 + 多选。
- 右栏成员管理 + 设置 + topic/goal banner。
- WS 订阅/退订 + 断线重连。
- **里程碑**：浏览器跑通"用户 @planer，planer @coder"接力。

### Phase 4 — Agent 自治 + 工作区（约 1 天）

- 3 个新工具：`chatroom_invite` / `chatroom_create_agent` / `chatroom_set_goal`。
- 工作区绑定注入 `workspace_root_override`。
- AgentRegistry 动态注册 + dynamic_members 持久化与重启重建。
- 手动验收剧本跑通。
- **里程碑**：录答辩 demo 视频。

**总工期估**：约 7 个工作日（含调试）。每阶段完成后跑全量测试 + manual smoke。

---

## 12. 关键设计决策与理由

| 决策 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 编排模型 | 召唤 / 主持 / 自由 / 混合 | 混合 | 默认 @ 召唤可控，Agent 互 @ 体现协作，主持模式作为加分项 |
| 上下文可见性 | 全公开 / 只看相关 / 公开+摘要 | 公开+摘要 | 群聊语义最自然；摘要应付长会话 |
| 通信模式 | 阻塞 / 流式异步 / 轮询 | 流式异步 | 复用现有 TaskRegistry+WS；接力链长时不卡用户 |
| 与 ChatPanel 关系 | 独立 / 改造 / 共享存储 | 独立模块独立存储 | 老功能零风险；演示时单聊 vs 群聊对照清晰 |
| Agent 创建审批 | 需批准 / 全自动 | 全自动 | 设计意图就是"全自动"协作，加批准会破坏闭环 |
| 动态 Agent 持久化 | 写回 yaml / 仅内存 + 房间 spec | 仅内存 + 房间 spec | 配置文件保持干净；房间状态自洽；重启可重建 |

---

## 13. 未决问题（实施期解决）

- **token 预算**：长群聊里"最近 N 条 + 摘要"的 N、M 默认值是否合理，需实测调参。
- **dispatch_agent 与聊天室的并存**：群聊里的 Agent 仍可调 `dispatch_agent` 派 SUB_AGENT 跑独立任务（不进群）。需确认 ContextVar `current_room_id` 不会被子 Agent 误读。计划：在 `dispatch_agent` 派子任务时显式 reset `current_room_id`。
- **WebSocket 频道订阅**：现有 handler 是否支持频道概念，若不支持需小幅扩展。Phase 2 启动时确认。

---

**文档状态**: v1.0 — 待实现
**最后更新**: 2026-05-26
