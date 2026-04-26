# 编排层 v2 设计（概念级）

**版本**: v2.0 设计稿
**日期**: 2026-04-26
**作者**: 项目维护者
**状态**: 设计阶段，未实现

> 本文档面向后续实现者，描述编排层从 **YAML 静态 DAG** 到 **反应式 Agent 工具循环 + 子任务派生** 的范式转变。
> 概念级，不出 Python 类签名；签名留给实现阶段补充。
> 设计参考 Claude Code 2.1.x（`claudecode-source/restored-src/src/`）的 QueryEngine / Task / Tool / Coordinator 子系统。

---

## 0. 为什么要重做编排层

### 0.1 v1 现状

当前编排由两条互不打通的链路构成：

| 链路 | 入口 | 调度逻辑 |
|------|------|----------|
| YAML 工作流 | `WorkflowOrchestrator.execute_template()` | 顺序/并行执行预定义步骤，按 `condition` 表达式跳过/重试 |
| 事件扳机 | `EventEngine.dispatch_event()` | 总线事件 → 匹配 Trigger → 调用 Agent.process() 一次 |

二者都把 **Agent 看作"输入 → LLM 一次调用 → 输出"的纯函数**。控制流（"接下来做什么"）在外部预先编排好。

### 0.2 v1 的根本局限

1. **Agent 不能用工具**：`assistant.process()` 只跑一轮 LLM 采样就返回，没有工具调用循环。`capabilities/tools/` 下 9 个工具（bash / file_search / web_fetch / ...）实际上没有真正可用的入口。
2. **子任务不可执行**：`PlannerAgent` 输出的子任务列表只是 JSON 字符串，被下游当作"上下文"塞给 `CoderAgent`，没有派生 / 调度 / 回收的语义。
3. **没有资源闸门**：除 timeout 和 max_iterations 外，没有 token 预算、USD 上限、边际收益终止。LLM 一旦死循环或回声，编排层无法干预。
4. **进度黑盒**：Agent 在跑就是在跑，外部只能等 `process()` 返回。前端无法看到"正在调用 X 工具"、"已用 N tokens"。
5. **无层级隔离**：所有 Agent 共享同一进程上下文，没有"父子" / "主-子代" 关系；无法做 abort 级联、独立工具池、独立 cwd / worktree。
6. **静态编排不实用**：现实中 Reviewer 是否要再跑一次 Coder 取决于 Reviewer 的判断，而不是 YAML 里写死的 `condition: review.passed == false`。

### 0.3 v2 范式

```
v1:   外部编排  →  Agent 一次性 LLM 调用  →  外部编排
v2:   Agent 自带工具循环 + 资源闸门  ⇄  派生子 Agent  ⇄  通过 notification 回注主会话
```

核心转变：**编排逻辑从 YAML 迁移到 Agent 自身的 LLM 推理中**。Planner 不再只输出"计划"，而是在自己的工具循环里直接派生 Coder 子 Agent；Reviewer 不再依赖 YAML 的条件分支，而是自己决定要不要再派生一次修复任务。

### 0.4 取舍声明

- **删除** `core/workflow/` 整个模块、`config/workflows.yaml`、前端 `WorkflowPanel`。
- **删除** `EventEngine` 的固定"扳机 → Agent.process 一次"链式调用（事件订阅本身保留，仅作 UI 通知用途，不再是编排手段）。
- **改造** `BaseAgent.process()` 为反应式工具循环。
- **保留** UnifiedBus、记忆系统、CapabilityRegistry、ContextStore（这些是基础设施，不属于编排层）。

---

## 1. 总览：八大支柱

```
┌─────────────────────────────────────────────────────────────┐
│  支柱 1: Agent 反应式工具循环（核心范式）                     │
│  ────────────────────────────────────────────────────────   │
│   while not done:                                            │
│      ① 调 LLM 采样 (流式)                                    │
│      ② 收集 tool_use 块                                      │
│      ③ 权限校验 → 并发/串行调度工具                          │
│      ④ 写回 tool_result，进入下一轮                           │
│      ⑤ 检查闸门：max_turns / token_budget / usd_ceiling      │
│      ⑥ 收尾：stop_hooks 钩子组、snip-boundary 压缩            │
└─────────┬─────────┬─────────┬─────────┬─────────┬───────────┘
          │         │         │         │         │
   ┌──────▼─┐  ┌────▼───┐  ┌──▼──┐  ┌───▼──┐  ┌───▼────┐
   │ 支柱 2 │  │ 支柱 3 │  │支柱4│  │支柱5 │  │支柱6/7 │
   │ Task   │  │ Tool   │  │子Agt│  │进度  │  │压缩与  │
   │ 抽象   │  │ 元数据 │  │隔离 │  │事件  │  │钩子    │
   └────────┘  └────────┘  └─────┘  └──────┘  └────────┘
                                              支柱8: Notification 回注
```

| 支柱 | 一句话职责 | 对应 Claude Code 文件 |
|------|----------|----------------------|
| 1 | Agent 自己跑工具循环直到模型停或闸门触发 | `QueryEngine.ts` |
| 2 | 异步工作（子 Agent / 后台任务）的统一抽象，含生命周期与 kill | `Task.ts` + `tasks/types.ts` |
| 3 | Tool 在执行前暴露元数据（只读 / 可并发 / 权限校验函数） | `Tool.ts` |
| 4 | 子 Agent 派生时的上下文 / 工具池 / cwd 隔离与 abort 级联 | `Tool.ts::createSubagentContext` |
| 5 | 增量进度上报：工具次数 / token / 当前活动 / 输出文件引用 | `tasks/types.ts::AgentProgress` |
| 6 | 长会话稳定点压缩历史，splice 边界，前段 GC | `QueryEngine.ts::snipReplay` |
| 7 | turn 末并发 stop hooks，可阻断本轮或终止迭代 | `query/stopHooks.ts` |
| 8 | 后台 Task 完成时以 user 角色 `<task-notification>` 回注主会话 | `coordinator/coordinatorMode.ts` |

下文逐支柱展开。每节固定结构：**职责 / 关键概念 / 与现有模块的关系 / 待决问题**。

---

## 2. 支柱 1：Agent 反应式工具循环

### 2.1 职责

让 Agent 自己掌控"一次任务"内的多轮 LLM 采样和工具调度，直到：

- 模型自然停止（`stop_reason == "end_turn"`）；
- 触达资源闸门（max_turns / token / USD / 边际收益）；
- 外部 abort 信号；
- stop hook 决议 `prevent_continuation`。

### 2.2 关键概念

- **Loop 拥有者**：每个 Agent 实例的一次"任务执行"对应一个 Loop。Loop 不是 Agent 的成员，而是一次 invocation 的运行时对象（类似 Claude Code 的 `QueryEngine` 实例）。
- **流式产出**：Loop 是 async generator，逐块产出（`message_start` / `content_block_delta` / `tool_use` / `tool_result` / `task_completed`），供 WebSocket 直接桥接到前端。
- **工具调度子阶段**：单轮 LLM 输出可能包含多个 `tool_use`。调度器按工具的 `is_concurrency_safe` 分组：可并发的批量 `asyncio.gather`，不可并发的串行。
- **资源闸门（Budget Gate）**：在每轮 tool round 后检查。
  - `max_turns`：最大对话轮次。
  - `token_budget`：累计输入 token 不超过预算的 90%。
  - `usd_ceiling`：累计 LLM 费用上限。
  - **边际收益启发式**：连续 3 轮新增 token < 500 时，认为 Agent 在原地踏步，强制终止。来自 `query/tokenBudget.ts` 的 `diminishing_returns` 判定。
- **闸门触发后的处理**：注入一条系统提示告诉 Agent "你只剩 X tokens / 还能跑 Y 轮"，给一次"收尾"机会；下一轮若仍未停则强制终止并以 `error_max_turns_reached` / `error_max_budget_*` 为原因返回。

### 2.3 与现有模块的关系

- `BaseAgent.process(data) → Dict` 改为 `BaseAgent.run(input) → AsyncIterator[StreamEvent]`。
- 旧 `process()` 方法可在过渡期保留为兼容包装（内部调用 `run()` 并消费整个流），但不推荐新代码使用。
- `EventEngine` 不再调度 Agent。事件订阅退化为 UI 通知（前端监控面板订阅总线，看 Agent 内部事件流）。

### 2.4 待决问题

- LLM Provider 抽象层（`core/llm/`）目前不暴露原生流式 API；需要在 `BaseLLMClient` 加 `stream_messages()` 接口。
- 闸门的 token 计数从哪里来？OpenAI/Anthropic 都在 `usage` 字段返回，需要在每轮采样后归集。

---

## 3. 支柱 2：Task 抽象

### 3.1 职责

为系统里 **所有异步工作** 提供统一的状态机、kill 接口、进度通道。"异步工作"包括：

- 主会话本身（`local_main_session`）；
- 派生的子 Agent（`local_agent`）；
- 协作型 Agent（`in_process_teammate`，多 Agent 共享上下文场景，可选）；
- 远程 Agent（`remote_agent`，跨进程，预留）；
- Shell 后台任务（`local_shell`，对应 `bash` 工具的 `run_in_background`）；
- MCP 监控（`monitor_mcp`，预留）；
- 长期记忆抽取（`dream`，对应记忆巩固后台任务，预留）。

### 3.2 关键概念

- **TaskStatus**：`pending → running → {completed | failed | killed}`，外加运行中的 `paused`（因等待权限确认）。
- **多态 kill**：每种 TaskType 自己实现 kill 语义（取消异步任务、关闭子进程、撤销订阅）。统一接口由 TaskRegistry 持有，不需要工厂模式。
- **磁盘 transcript（output_file）**：每个 Task 有自己的 JSONL 输出文件。运行中流式追加，结果不重新塞进父进程内存。父进程只保留 `output_offset` 用于增量读取。
- **GC 策略**：Task 终态后挂 `evict_after = now + N` 戳；后台 GC 周期清理过期的 transcript。父任务若仍持有引用可设 `retain` 标记延迟回收。
- **TaskRegistry**：进程级单例，按 task_id 存所有 Task 状态；前端通过 `GET /api/tasks` 拉列表。

### 3.3 状态机

```
            ┌────────────┐
            │  pending   │
            └─────┬──────┘
                  │ schedule
                  ▼
            ┌────────────┐
            │  running   │◄────┐
            └─────┬──────┘     │ resume(权限通过)
       完成        │ abort/钩子│
       ┌──────────┤           │
       │          │           │
       ▼          ▼           │
┌──────────┐ ┌─────────┐  ┌───┴─────┐
│completed │ │ failed  │  │ paused  │
└──────────┘ └─────────┘  └─────────┘
       ▲          ▲           │
       │          │           │ user kill
       └──────────┴───────────┴─────► killed
```

### 3.4 与现有模块的关系

- 完全替换 `core/workflow/types.py::Task`（那是 workflow step 的概念，与本文 Task 不同）。
- 新建 `core/task/` 目录承载 TaskRegistry、TaskState、各 TaskType 实现。
- API 层 `routes/tasks.py` 改为操作 TaskRegistry。

### 3.5 待决问题

- transcript 落盘位置：`./data/tasks/{task_id}.jsonl`？需要和现有 `data/` 目录约定。
- `paused` 状态需要前端的"批准/拒绝"交互，UI 怎么呈现？等待 UI 设计另议。

---

## 4. 支柱 3：Tool/Agent 元数据驱动执行

### 4.1 职责

让 Tool 在被 Agent 调用前 **先暴露行为元数据**，让调度器据此决定：

- 是否可以和别的 tool 并发跑；
- 是否需要权限弹窗；
- 是否对副作用敏感（影响 audit log 记录粒度）；
- 输出是否要走 result budget 截断。

### 4.2 关键概念

- **`is_read_only(input)`**：纯读、不改文件 / 不发请求 / 不耗费配额的工具返回 True。决定是否记入 audit log 的"可疑操作"。
- **`is_concurrency_safe(input)`**：本次 input 下可否和别的 tool_use 并发。例：`read_file` 无副作用 → True；`write_file`、`bash` → False。注意是 **per-input** 检查，不是 per-tool 标志：`bash` 跑 `ls` 是安全的，跑 `npm install` 不是。Claude Code 把这判断交给工具自己决定。
- **`check_permissions(input, ctx) → PermissionDecision`**：运行时函数，不是布尔值。返回三种之一：
  - `allow`：直接执行；
  - `deny(reason)`：拒绝；
  - `modified(new_input)`：改写输入后再执行（例：用户在 UI 里编辑了 `bash` 命令）。
- **`max_result_size`**：单次 tool_result 字符上限。超出时落盘到 task 的 `output_file`，model 看到的是引用，不是全文。这就是 **Tool Result Budget**（v1 没有，是新设计）。
- **`description(input) → str`**：动态描述。`bash("rm -rf /")` 的描述应是 "执行 rm -rf /"，不是静态的 "运行 shell 命令"。给前端权限确认弹窗用。

### 4.3 元数据驱动的执行流程

```
LLM 输出 N 个 tool_use 块
    │
    ▼
分组：按 is_concurrency_safe(input) 切两组
    │
    ├─► 并发组：asyncio.gather(...)
    │         每个先 check_permissions → 执行 → 截断输出
    │
    └─► 串行组：for tool in group: ...
              每个先 check_permissions → 执行 → 截断输出
    │
    ▼
所有 tool_result 拼回模型上下文，进入下一轮
```

### 4.4 与现有模块的关系

- `core/capability/base.py::CapabilityBase` 增加上述元数据字段（默认实现 `is_read_only=False, is_concurrency_safe=False, check_permissions=allow`，老能力按需重写）。
- `capabilities/tools/_safety.py` 已有的命令白名单逻辑迁移到 `bash.check_permissions()`。
- `CapabilityRegistry` 不变；它只是注册中心。

### 4.5 待决问题

- 权限弹窗交互：MVP 先在后端日志里记录 `paused` 决策，前端弹窗放后续；这要求 Loop 支持 `paused` 状态恢复。
- `modified(new_input)` 的输入校验在哪做？建议复用 Tool 的 Pydantic schema 二次校验。

---

## 5. 支柱 4：子 Agent 隔离

### 5.1 职责

让父 Agent 通过工具（命名为 `agent` 或 `dispatch_agent`）派生一个子 Agent 跑独立任务，**不污染父上下文**，并保留 abort / 进度 / 结果回收的层级关系。

### 5.2 关键概念

- **独立上下文**：子 Agent 启动时 clone 一份 AppState（系统提示、工具池、记忆访问句柄），但消息历史 **完全独立**，从空白开始。父 Agent 看不到子 Agent 的中间消息。
- **独立工具池**：子 Agent 的可用工具是父工具池的 **子集**。MVP 的策略：
  - 子 Agent 默认拿到的工具：read_file / file_search / bash（read-only 命令）/ web_fetch / memory_search。
  - 子 Agent **不能再派生孙 Agent**（避免无限递归）；后续可放开但要限制 `max_depth`。
- **可选 worktree / cwd 隔离**：子 Agent 可声明"我要在独立 git worktree 跑"，由调度器创建临时 worktree，子 Agent 终态后清理。文件写操作隔离。**v1 没有这能力**，是新设计。
- **父子 abort 链**：父 Agent kill 时，所有未完成的子 Agent task_id 自动级联 kill。父子关系存在 `Task.parent_id` 字段。
- **query depth**：子 Agent context 里带 `query_depth = parent.query_depth + 1`，便于追踪嵌套层级（即便禁止孙 Agent，仍方便日志分析）。

### 5.3 派生与回收时序

```
父 Agent       Loop          TaskRegistry      子 Agent Loop
   │             │                 │                 │
   │── tool_use(agent, prompt) ────►                  │
   │             │                 │                 │
   │             │── create_task ──►                  │
   │             │                 │── spawn ────────►│
   │             │                 │                 │ (运行)
   │             │                 │◄── progress ─────│
   │ ◄─ tool_result(task_id) ──    │                 │
   │  (注：父此时立即拿到 task_id    │                 │
   │   但子 Agent 还在跑)           │                 │
   │             │                 │◄── completed ────│
   │             │                 │                 │
   │             │   <task-notification> 注入主会话   │
   │ ◄────── 用 user 角色塞回主历史 ─────────          │
   │             │                                   │
   │ (下一轮 LLM 看到 notification 决定下一步)         │
```

注意：**父 Agent 不阻塞等子 Agent**。tool 调用立即返回 `task_id`，子 Agent 在后台跑；完成后通过支柱 8 的 notification 机制把结果"以用户消息形式"塞回主会话。这让父 Agent 可以同时派多个子 Agent 并发干活。

### 5.4 与现有模块的关系

- 新增 tool `agent`（在 `capabilities/tools/agent.py`）。
- 子 Agent 派生需要 LLM 客户端、工具池、记忆引用等基础设施 → 通过 `SubAgentContext` 注入。
- `core/agent/registry.py` 不变；子 Agent 也是 Agent 的实例，只是 Context 不同。

### 5.5 待决问题

- worktree 隔离的清理策略：子 Agent 失败（killed/failed）时是否保留 worktree 供调试？建议参考 Claude Code 的 ExitWorktree 行为，提供 `keep` / `remove` 两种结束方式。
- 子 Agent 是否可访问父的记忆？默认共享 read-only，写入仅限父。

---

## 6. 支柱 5：进度事件

### 6.1 职责

让外部观察者（前端 UI、日志系统、其他 Agent）实时看到 Agent 内部状态，**不需要等 Loop 结束**。

### 6.2 关键概念

- **AgentProgress 数据结构**：由 Loop 周期发射，至少包含：
  - `tool_count`：当前 task 已调用工具次数。
  - `total_tokens`：累计输入+输出 token。
  - `activity`：人类可读的当前活动描述（"正在搜索文件 \*.py"、"正在调用 bash"、"等待 LLM 响应"）。
  - `last_tool`：最近一次工具的名字 + 输入摘要。
  - `output_file_offset`：transcript 文件的字节偏移，前端可增量拉取。
- **发射时机**：每次 tool_round 边界、每次 LLM 流式块到达、每次状态切换。
- **传输通道**：通过 UnifiedBus broadcast；WebSocket Handler 订阅特定 task_id 的进度事件转发给前端。

### 6.3 与现有模块的关系

- `core/bus/unified_bus.py::broadcast()` 已有，复用。
- 前端 `MonitorPanel` 增加"按 task 看进度"视图；`TaskPanel` 改为显示 AgentProgress 而不是当前的"plan_request → plan_created → ..." 文字流。

### 6.4 待决问题

- 高频进度事件可能压垮 WebSocket：需要节流（throttle 到 5Hz？前端聚合？）。

---

## 7. 支柱 6：历史压缩（Snip-boundary Compaction）

### 7.1 职责

长会话里 LLM 上下文容易撑爆。在 Agent 自己判定"现在是稳定边界"时（无未完成 tool_use）插入一个"snip 标记"，调度器按标记把前段历史压成一条 system 消息，前段消息从内存释放。

### 7.2 关键概念

- **稳定边界**：LLM 输出 `stop_reason == "end_turn"` 且本轮没有未完成的 tool_use。即所有工具都跑完了、模型也"说完了"。在这种点上，截断不会丢失正在进行的状态。
- **压缩策略**：MVP 用 LLM 自己写"前 N 条消息的摘要"，替换前段。摘要生成本身可以用一个轻量模型（haiku）异步跑，不阻塞主 Loop。
- **splice**：压缩后的消息序列是 `[summary_message, ...recent_messages_after_snip]`，前段对象可以释放给 GC。
- **触发条件**：`累计输入 token > 阈值（例如预算的 70%）` 时，下一个稳定边界自动 snip。也允许用户手动 `/snip` 命令。

### 7.3 与现有模块的关系

- 是 Agent Loop 的内部机制，不影响其他模块。
- 长期记忆系统（`core/memory/`）独立运作；snip 压缩只针对单次 task 的对话历史，不替代记忆系统。

### 7.4 待决问题

- 子 Agent 是否需要 snip？子 Agent 通常生命周期短，可 MVP 不实现。
- 摘要质量评估：被截断的消息再被 LLM 引用时是否会丢信息？需要测试用例验证。

---

## 8. 支柱 7：Stop Hooks

### 8.1 职责

在每一轮 tool_round 结束、即将进入下一轮 LLM 采样之前，**并发执行用户配置的钩子组**，钩子可以：

- 报告错误（让本轮失败但不终止 Loop）；
- 决定 `prevent_continuation`（让 Loop 优雅终止，原因写入返回值）；
- 写额外消息到 transcript（例：自动跑 lint 报告）。

### 8.2 关键概念

- **HookSpec**：配置驱动，至少含 `name`、`command`（shell）、`timeout`、`blocking`（错误是否阻断本轮）。
- **执行时机**：每轮 LLM 采样后、tool_use 调度前。即 "模型说完话 → 钩子先跑 → 看要不要继续工具调度"。
- **结果聚合**：所有钩子并发跑，收集 stdout/stderr/exit_code，汇总成一条 system 消息塞进 transcript（让 Agent 在下一轮看到钩子反馈）。
- **配置位置**：`config/stop_hooks.yaml`，可按 Agent 名字过滤（例 "Coder 完成时跑 lint，Reviewer 不跑"）。
- **关键约束**：钩子是 **本地用户脚本**，要走和 `bash` 工具同样的安全策略；不能让 LLM 间接动态生成钩子。

### 8.3 用例

- 代码生成完跑 `ruff check` / `pytest -q`，失败时阻断本轮。
- Agent 终态时触发 "auto-dream"（把本次 task 经验抽取成长期记忆）。
- 给前端推送"Agent 任务即将结束"通知。

### 8.4 与现有模块的关系

- 新增 `core/agent/stop_hooks.py` 模块。
- 新增 `config/stop_hooks.yaml` 配置文件。
- 与记忆系统的"记忆形成"流程对接：可作为一个内置 hook 实现。

### 8.5 待决问题

- 钩子失败时给 Agent 看到的提示格式：直接糊 stderr？还是结构化 JSON？建议 JSON，让 Agent 可解析。

---

## 9. 支柱 8：Notification 回注

### 9.1 职责

后台 Task（特别是子 Agent）完成时，**结果不应该躺在 TaskRegistry 等父 Agent 主动轮询**，而应该作为一条 user 角色消息塞回父 Agent 的会话历史，让父 Agent 在下一轮自然看到结果并决定后续动作。

### 9.2 关键概念

- **`<task-notification>` 结构**（参考 Claude Code coordinatorMode.ts）：
  ```xml
  <task-notification>
    <task-id>...</task-id>
    <status>completed|failed|killed</status>
    <summary>...</summary>
    <result>...</result>
    <usage>
      <total_tokens>N</total_tokens>
      <tool_uses>N</tool_uses>
      <duration_ms>N</duration_ms>
    </usage>
  </task-notification>
  ```
- **以 user 角色塞回**：这点是反直觉但关键。LLM 看到的就是"用户给我发了一条带 XML 标签的消息"。父 Agent 的系统提示里说明 `<task-notification>` 的语义，让它知道"这其实是子 Agent 完成报告，不是真用户输入"。
- **回注时机**：父 Agent 当前在等模型回复（即不在 tool round 中间）时立即注入；如果父 Agent 还在跑工具，notification 入队，下一轮 tool_round 边界塞入。
- **多个 notification 聚合**：父 Agent 同时派了 3 个子 Agent，第 1 个完成时不立即触发父继续；等到下一轮模型采样前一次性把所有已完成的 notification 都塞进去。

### 9.3 与支柱 5（子 Agent 隔离）的对比

- 派生 (支柱 5) 是 **派出去**：父 Agent 调 `agent` 工具拿到 `task_id`，立即返回继续干别的。
- 回注 (支柱 8) 是 **回得来**：子 Agent 完成时把结果送回主会话，父 Agent 不需要主动等。
- 两者配合：父 Agent 可以并发派 N 个子 Agent，自己继续做主线工作，结果以 notification 流陆续到达。

### 9.4 与现有模块的关系

- 复用 UnifiedBus 的 broadcast：子 Task 完成时 broadcast `task_completed`，父 Loop 订阅自己 task_id 下游的所有 task。
- 父 Loop 的"下一轮 LLM 采样前"hook 把累积的 notification 打包写入消息历史。

### 9.5 待决问题

- 父 Agent 已经死循环（被 kill）时，子 Agent 的 notification 如何处理？记入 transcript 即可，不主动唤醒父。
- notification 太长（result 字段几千字符）怎么办？走支柱 3 的 result budget 截断到 output_file 引用。

---

## 10. 与现有模块的取舍清单

| 模块 / 文件 | 处置 | 理由 |
|------------|------|------|
| `core/workflow/orchestrator.py` | **删除** | 静态 DAG 的责任由 Agent 工具循环 + 子 Agent 派生承担 |
| `core/workflow/types.py` | **删除** | `Task` 概念被支柱 2 的 Task 替换，名字冲突 |
| `config/workflows.yaml` | **删除** | 不再有外部预编排步骤 |
| `frontend/.../WorkflowPanel.*` | **删除** | UI 不再有"工作流"概念，对应改为"Task 列表"+"Task 详情" |
| `core/event/engine.py` | **降级** | 仅保留事件订阅做 UI 通知；不再做"扳机 → Agent 调用"的编排 |
| `config/triggers.yaml` | **删除或缩减** | 同上；保留少量"事件 → 通知"映射即可 |
| `core/agent/base.py` | **改造** | `process()` 改为 `run()` async generator |
| `core/agent/registry.py` | 保留 | 仅是发现/注册中心，不参与编排 |
| `core/agent/lifecycle.py` | 保留 | Agent 进程级生命周期与 Task 生命周期是两层，互不冲突 |
| `core/bus/unified_bus.py` | 保留 | 进度事件、notification、UI 通知全靠它 |
| `core/memory/*` | 保留 | 与编排正交 |
| `core/capability/*` | **扩展** | CapabilityBase 增加元数据字段（支柱 3） |
| `capabilities/tools/_safety.py` | **迁移** | 命令白名单从全局守卫迁到 `bash.check_permissions()` |
| `core/llm/base.py` | **扩展** | 增加 `stream_messages()` 接口 |
| `core/context/store.py` | 保留 | 三层作用域上下文与 SubAgentContext 不冲突 |
| 新增 `core/task/` | **新增** | TaskRegistry / TaskState / 各 TaskType 实现 |
| 新增 `core/agent/loop.py` | **新增** | Agent 反应式 Loop 主体 |
| 新增 `core/agent/stop_hooks.py` | **新增** | Stop Hooks 调度 |
| 新增 `core/agent/snip.py` | **新增** | 历史压缩 |
| 新增 `core/task/notifier.py` | **新增** | Task 完成 → notification 注入 |
| 新增 `capabilities/tools/agent.py` | **新增** | 派生子 Agent 工具 |
| 新增 `config/stop_hooks.yaml` | **新增** | 钩子配置 |
| 新增 API `routes/tasks.py` | **重写** | 操作 TaskRegistry，支持 list/detail/kill/progress 流 |

---

## 11. 实现路线图（不含代码）

分四阶段，每阶段独立可验收。

### Phase A：Agent 工具循环底盘（最关键） ✅ 已落地（2026-04-26）

支柱 1 + 支柱 3 的最小集。**已实施改动**（探查后确认 LLM 流式接口与 generic `Agent.run/run_stream` 早已就位，因此 Phase A 主要补的是元数据驱动调度、Result Budget、Token 闸门、WebSocket 流式接入和过期代码清理）：

- ✅ `CapabilitySchema` 增 `is_read_only / is_concurrency_safe / max_result_size` 字段
- ✅ `CapabilityBase.check_permissions(**kwargs)` 默认实现（运行时函数，可返回 allow/deny + reason）
- ✅ 12 个内置 tool 完成元数据标注；`bash.check_permissions` 走 `_safety` 校验
- ✅ `Agent._dispatch_tool_calls` 按 `is_concurrency_safe` 切两组：可并发组 `asyncio.gather`，不可并发组串行
- ✅ `Agent._execute_with_permission` 在执行前调 `check_permissions`，deny 时不调 `execute`，错误回写 LLM
- ✅ `Agent._apply_result_budget` 单工具结果超 `max_result_size` 时截断 + 标记 `truncated: true`
- ✅ `Agent` 增 `token_budget` / `token_budget_nudge_threshold` 参数：超 85% 阈值插 system 提醒，超 100% 强制终止
- ✅ `_create_agents_from_config` 透传 `token_budget`；`config/agents.yaml` 给 assistant=120k、coder=200k
- ✅ WebSocket `_handle_user_message` 接 `AgentCapability.execute_stream`，下发 `agent_thinking / agent_tool_call / agent_tool_result / agent_done`，保留 `assistant_response` 兼容旧前端
- ✅ 删除 `BaseAgent` ABC、4 个死 Agent 子类（`agents/{assistant,planner,coder,reviewer}.py`）、`backend/config/agents.yaml`、`example_simple.py`、`core/agent/__init__.py` 的 `BaseAgent = Agent` 别名、`core/event/engine.py` 对 `BaseAgent` 的硬依赖
- ✅ 新增 6 个单测覆盖并发分组 / 串行 / 截断 / 权限 deny / 预算硬终止 / 预算 nudge（`backend/tests/unit/test_agent_loop_phase_a.py`）

**验收**：573 个测试全绿；前端 WebSocket 现在收到流式工具调用事件；assistant 触达 120k token 自动收尾。

**仍未做的（明确留给后续 Phase）**：
- USD 上限、边际收益启发式（diminishing returns）→ Phase D
- Tool result 落盘 + 可读引用 → Phase B（Task 抽象有 output_file）
- Permission `modified(input)` 决策 + 前端弹窗 → Phase D
- EventEngine / TriggerRegistry / `core/event/*` 整体清理 → Phase B（与 workflow 一起删）
- `backend/config/{capabilities,system,triggers,workflows}.yaml` 过期副本清理 → Phase B

### Phase B：Task 抽象 + 进度 ✅ 已落地（2026-04-26）

支柱 2 + 支柱 5 + 拆掉旧 workflow + Workflow→Pipeline 重命名。**已落地（2026-04-26）**：

- ✅ 新建 `core/task/` 模块：`TaskState`、`TaskStatus`、`TaskType`、`AgentProgress`、`TaskRegistry`、`TranscriptWriter` / `read_transcript`
- ✅ `Pipeline.execute()` 增 `on_step_event` 回调，每步骤 started/completed/failed/skipped 时触发；不破坏现有 bus 通知路径
- ✅ 重写 `routes/tasks.py`：用 TaskRegistry 替代旧 `_tasks` 字典；DELETE 真正 cancel asyncio.Task；新增 `GET /api/tasks/{id}/transcript`
- ✅ Transcript 落盘：`data/tasks/{task_id}.jsonl`，含 created/started/step_*/done/killed/error 事件
- ✅ 前端 `TaskPanel` 增强：显示 `progress`（tool_count / total_tokens / current_step / activity）+ 取消按钮；轮询保留 5s
- ✅ Workflow → Pipeline 重命名（破坏性）：路由 `/api/workflows/*` → `/api/pipelines/*`、配置 `config/workflows.yaml` → `config/pipelines.yaml`（顶层 key `workflows:` → `pipelines:`）、前端 `WorkflowPanel.{tsx,css}` → `PipelinePanel.*`、`Sidebar` "工作流" → "管线"、Schemas `Workflow*` → `Pipeline*`、`SystemConfig.workflow` → `SystemConfig.pipeline`
- ✅ 死代码清理：删除 `backend/src/core/workflow/`、`backend/src/core/event/`、`backend/config/`（5 个过期 yaml）、`config/triggers.yaml`；解除 `core/event/engine.py` 的所有依赖
- ✅ 测试：新增 `test_task_registry.py`（7 用例）、`test_transcript_writer.py`（4 用例），改造 `test_pipeline_and_workflow.py` → `test_pipeline.py`（去掉 Workflow 部分）；587 通过零退化

**仍未做的（明确留给后续 Phase）**：
- chat 不进 Task（用户决议）；TaskPanel 仅显示 pipeline 任务，不显示 WebSocket 对话
- WebSocket 推送 progress（仍 5s 轮询）→ Phase C
- Transcript GC（evict_after）→ Phase D
- 子 Agent 派生 / `<task-notification>` 回注 → Phase C
- TaskState `ended_at` 与 `output_file` 已落字段，但 GC / 大文件压缩留 Phase D

**验收**：通过 `POST /api/tasks` 提交任务 → `GET /api/tasks/{id}` 看到 `progress.current_step` 推进 → `GET /api/tasks/{id}/transcript` 拿到 step_* 事件流 → `DELETE /api/tasks/{id}` 取消时状态变 `killed`。

### Phase C：子 Agent 派生 + Notification 回注 ✅ 已落地（2026-04-26）

支柱 4 + 支柱 8。**已实施改动**：

- ✅ `core/task/context.py` 新增 4 个 `ContextVar`：`parent_task_id` / `notification_box` / `workspace_root_override` / `dispatch_depth`（跨 async 调用栈传递运行时状态）
- ✅ `core/task/notifications.py` 新增 `format_task_notification(payload) -> XML` + `make_user_message`，输出格式参考 Claude Code coordinatorMode；自动 XML 转义防止注入；result 超 2000 字符截断
- ✅ `core/task/types.py` 新增 `TaskType.SUB_AGENT`
- ✅ `core/task/registry.py::TaskRegistry.kill` 改造为递归级联：父 task 取消时所有未终态的子 task 一并 cancel；新增 `list_children(parent_id)`
- ✅ `core/agent/agent.py::Agent.run / run_stream` 入口建 `notification_box: List[Dict]`，挂到 contextvar；每轮 LLM 采样前 `await asyncio.sleep(0)` 让出事件循环 + drain box → `<task-notification>` user 消息追加到 messages
- ✅ `capabilities/tools/_safety.py::get_workspace_root` 优先看 `workspace_root_override` contextvar，让 dispatch_agent worktree 模式覆盖文件 tool 工作根
- ✅ `capabilities/tools/dispatch_agent.py` 新增 `DispatchAgentCapability`：
  - 解析 `subagent_type` → `CapabilityRegistry`，找不到返 error
  - `check_permissions` + execute 双重校验 `dispatch_depth >= 1`（MVP 禁止嵌套派生）
  - 可选 `worktree=true`：用 `git worktree add --detach` 在 `data/worktrees/{task_id}/` 建临时 worktree
  - 创建 `TaskType.SUB_AGENT` 子 task；asyncio.create_task 派生 `_run_subagent` 后台跑；attach 句柄到 registry
  - 完成 / 失败 / cancel 时回写 TaskRegistry + 父 notification_box + transcript
  - 立即返回 `{task_id, status="dispatched", summary, worktree}`，不阻塞父 Agent
- ✅ `routes/tasks.py::_run_pipeline_task` 和 `_run_single_agent_fallback` 用 `set_parent_task_id` 包裹执行；try/finally reset
- ✅ `config/agents.yaml`：`planner.tools` + `coder.tools` 末尾加 `dispatch_agent`；system_prompt 加使用指引
- ✅ 测试：`test_notifications.py`（6 用例）+ `test_task_registry.py` 增 `test_kill_cascades_to_child_tasks` / `test_list_children` + `test_dispatch_agent.py`（8 用例：立即返回 / 嵌套保护 / 未知 subagent / 缺参 / 端到端 notification 回注 / failed sub-agent）；605 → 619 通过零退化

**仍未做的（明确留给后续 Phase）**：
- Worktree GC（evict_after / 自动清理）→ Phase D
- 跨 commit / push 的 worktree 操作 → 不实装（子 Agent 在 worktree 内只读写文件）
- MCP 远程子 Agent → 预留接口
- 嵌套派生（max_depth ≥ 2）→ MVP 不做
- Notification 持久化 / 重试 → 不做（in-memory 即可）

**验收**：
- 单测验证 dispatch_agent 异步派发 + notification 端到端回注 user role messages（`test_notification_appears_in_parent_messages`）
- 父 task DELETE 时所有 SUB_AGENT 子 task 级联 KILLED（`test_kill_cascades_to_child_tasks`）
- `test_check_permissions_denies_at_max_depth` 验证嵌套派生在 schema 层就被拒

### Phase D：高级特性

支柱 6 + 支柱 7。

- Snip-boundary 历史压缩
- Stop Hooks 调度 + 配置
- 长会话稳定性测试
- 文档更新到"已实现"

**验收**：单次 task 跑 50+ 轮工具循环不爆 context；stop_hooks 能成功阻断有 lint 错的代码生成。

---

## 12. 待决议的开放问题汇总

| # | 问题 | 提议方向 |
|---|------|----------|
| Q1 | LLM Provider 流式接口在 OpenAI / Anthropic / DeepSeek 三家是否能统一？ | 三家 SDK 都有 stream 模式，抽象层统一返回 `AsyncIterator[StreamChunk]` |
| Q2 | Tool Result Budget 截断后引用怎么让 model "看回去"？ | 给 Agent 提供 `read_task_output(task_id, offset)` 工具 |
| Q3 | 子 Agent 是否可以再派孙 Agent？ | MVP 禁止，加 `max_depth=1`；后续放开到 2 |
| Q4 | 子 Agent worktree 失败时保留还是清理？ | 默认保留供调试，配 `evict_after = 1h` 后自动清 |
| Q5 | Stop Hook 失败重试策略？ | 不重试，hook 应该幂等；失败信息让 Agent 自己决定怎么办 |
| Q6 | Notification XML 包不进当前消息怎么办（父 Agent 已 killed）？ | 仅记入父 transcript 文件，不唤醒父，UI 列表里仍可见 |
| Q7 | 主会话和子 Agent 是否共享 UnifiedBus？还是子 Agent 用本地 bus？ | 共享；订阅按 task_id 过滤即可 |
| Q8 | 现有 4 个内置 Agent（Assistant/Planner/Coder/Reviewer）的边界还有意义吗？ | 仍有：每个 Agent 系统提示不同、工具池不同。但调度从"YAML 串起来"改为"Agent 派生"。 |

---

## 13. 与 v1 的对照速查

| 场景 | v1 怎么跑 | v2 怎么跑 |
|------|----------|----------|
| 用户问"帮我修一个 bug" | `assistant.process()` 调一次 LLM，回字符串 | Assistant Loop 跑工具循环：file_search → read_file → bash(测试) → write_file → bash(再测) → 完成 |
| 完整代码生成与审查 | YAML workflow `code_generation_and_review` 顺序跑 Planner → Coder → Reviewer → 条件分支 Coder | Planner Loop 内部决定派 Coder 子 Agent，notification 回来后决定要不要派 Reviewer，再决定要不要派修复 |
| 用户中途想取消 | 等 timeout，没有取消接口 | DELETE /api/tasks/{id} → kill() 级联 |
| 想看 Agent 进度 | 看不到，只能等结果 | TaskPanel 实时显示 AgentProgress |
| 一次任务用了多少钱 | 没记录 | TaskState 记录 `usage.usd_cost`，可达上限自动停 |
| Agent 死循环 | 撞 max_iterations 才停 | 边际收益启发式提前止损 |
| 长会话历史爆 context | 没有处理 | snip-boundary 自动压缩 |
| 代码生成完想自动跑 lint | 没有钩子，得手动 | stop_hooks.yaml 配一行就行 |

---

**文档状态**：v2.0 设计稿（概念级）
**下一步**：Phase A 实现前补 LLM Provider 流式接口的接口签名草案；其余支柱在动工时逐项细化为类签名后再实现。
