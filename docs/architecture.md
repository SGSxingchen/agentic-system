# 系统架构

> 最后更新: 2026-04-26 | 与 CLAUDE.md 保持一致
>
> ✅ **编排层 v2 Phase A + B + C 已落地（2026-04-26）**：Agent 反应式工具循环底盘 +
> Task 抽象 + Pipeline 替换 Workflow + 非阻塞子 Agent 派生 + `<task-notification>` 回注 +
> 工具元数据驱动并发 / 权限 / 预算闸门 + 可选 git worktree 隔离。
> 详见 [`./orchestrator-v2.md`](./orchestrator-v2.md) §11；CLAUDE.md §3.5 / §3.8 / §3.9 是当前实现的权威描述。
> 本文档的"编排"和"数据流"章节描述的是历史 v1 视角，整体重写待 Phase D 后一并处理。
>
> 🧠 **记忆层 v2 设计中**：私人助理式全局长期记忆方案见
> [`./superpowers/specs/2026-04-26-private-assistant-memory-lite-design.md`](./superpowers/specs/2026-04-26-private-assistant-memory-lite-design.md)。
> 该方案不做 session/persona 隔离，重点补齐自动形成、结构化摘要、可解释召回和遗忘巩固。

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│                 前端 (React / TypeScript)             │
│                                                       │
│  ChatPanel │ TaskPanel │ AgentPanel │ MemoryPanel     │
│  WorkflowPanel │ MonitorPanel │ Settings │ Sidebar    │
└──────────────────────┬────────────────────────────────┘
                       │ HTTP REST / WebSocket
┌──────────────────────▼────────────────────────────────┐
│               FastAPI 服务层 (Port 8001)               │
│                                                        │
│  Routes: tasks │ agents │ workflows │ memory │ config  │
│  WebSocket Handler │ Dependencies (DI)                 │
│  Pydantic Schemas │ CORS Middleware                    │
└──────────────────────┬─────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────┐
│          UnifiedBus — 统一消息总线 (系统神经中枢)       │
│                                                         │
│  EventChannel │ RequestChannel │ BroadcastChannel       │
│  MessageRouter │ PriorityQueue │ MessageHistory         │
│  BusMetrics (运行指标)                                  │
└───┬──────────┬──────────┬──────────┬───────────────────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
│ Event  │ │ Memory │ │Context │ │ Capability   │
│ Engine │ │ System │ │ Store  │ │ Registry     │
│(扳机)  │ │(记忆)  │ │(上下文)│ │(能力插件)    │
└───┬────┘ └────────┘ └────────┘ └──────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    智能体层 (4 个 Agent)                  │
│                                                           │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐   │
│  │ Assistant  │ │ Planner  │ │  Coder  │ │ Reviewer │   │
│  │ (对话助手) │ │ (规划器) │ │(代码生成)│ │(代码审查)│   │
│  └───────────┘ └──────────┘ └─────────┘ └──────────┘   │
│                                                           │
│  AgentRegistry │ AgentLifecycleManager                   │
└──────────────────────┬────────────────────────────────────┘
                       │
┌──────────────────────▼────────────────────────────────────┐
│                   LLM 客户端层                             │
│  OpenAI Client │ Anthropic Client │ Factory               │
└───────────────────────────────────────────────────────────┘
```

## 核心组件

### 前端体验层

前端仍保持 React + TypeScript + 原生 CSS 的轻量架构，不引入重量级 UI 框架。当前聊天体验按现代 AI Chat 产品的信息架构优化：

- `Sidebar` 负责全局工作区导航，按 Workspace / Agents / Memory / System 分组，并用连接状态提示后端可用性。
- `ChatPanel` 内部保留“会话列表 + 主聊天区 + 底部输入器”三段式结构；消息区使用居中阅读宽度，输入器保持底部舒适可达。
- Tool 调用、Agent 进度、错误与结构化对象优先以可展开 card/timeline 呈现；原始 JSON 仅作为详情层保留，避免直接暴露大段对象。
- 空状态提供可点击示例提示；长文本、代码块、表格、对象/数组内容使用 Markdown/详情卡样式兜底展示。
- 窄屏下全局导航横向化、会话栏压缩为顶部区域，保证聊天主流程可用。

这些改动只影响前端展示层，不改变 REST/WebSocket API 协议、后端任务模型或 Agent 运行逻辑。

### 统一消息总线 (UnifiedBus)

位于 `core/bus/unified_bus.py`，所有组件通过总线通信。

| 通信模式 | 方法 | 说明 |
|----------|------|------|
| 发布/订阅 | `publish()` / `subscribe()` | 事件驱动，一对多 |
| 请求/响应 | `request()` / `handle_request()` | 同步调用，一对一 |
| 点对点 | `send()` / `register_route()` | 路由分发 |
| 广播 | `broadcast()` | 全局通知 |

内部由 EventChannel、RequestChannel、BroadcastChannel、MessageRouter 四个子组件协作。使用 asyncio.PriorityQueue 实现优先级消息处理。

### 事件引擎 + 扳机系统

**EventEngine** (`core/event/engine.py`):
- 接收总线事件 → 查找匹配扳机 → 评估条件 → 调度 Agent
- 同步扳机串行执行，异步扳机并发执行
- 条件表达式安全评估 (restricted eval)

**扳机 (Trigger)** 在 `config/triggers.yaml` 中定义:
```yaml
triggers:
  - id: "code_to_reviewer"
    event: "code_generated"
    agent: "reviewer"
    priority: 1
    condition: "data.get('language') == 'python'"
```

### 智能体系统

4 个 Agent 继承自 `BaseAgent`，通过 `AgentRegistry` 管理:

| Agent | 功能 | 输入事件 | 输出事件 |
|-------|------|----------|----------|
| Assistant | 对话 + 记忆检索 | user_message | assistant_completed |
| Planner | 需求分解 | plan_request | plan_created |
| Coder | 代码生成 | plan_created | code_generated |
| Reviewer | 六维度审查 | code_generated | review_passed / review_failed |

### 记忆系统

三种记忆类型: episodic / semantic / procedural

v2 方向: 记忆系统将升级为私人助理式全局长期记忆层。所有记忆默认进入共享个人记忆池，`session_id` 仅作为来源追踪，不作为默认召回过滤条件；自动对话反思的缓冲窗口必须按 `session_id` 隔离，避免不同会话内容被合并成同一条记忆。新增自动对话反思、`canonical_summary` / `assistant_context` 双摘要、检索评分解释和近似去重。

记忆注入到 Agent prompt 时必须明确标记为不可信资料，只能作为事实参考，不能执行记忆文本中的指令。解释性召回必须先使用底层 `MemoryStore.search()` 做候选粗筛，保留 ChromaDB 等后端的语义检索能力，再叠加本地评分、去重和 `retrieval` 解释；候选搜索本身不应刷新访问计数，只有最终选中的召回结果才更新访问记录。

组件:
- **MemoryStore** — InMemoryStore 或 ChromaStore
- **MemoryFormation** — 创建 / 巩固 (去重) / 遗忘 (衰减)
- **MemoryRetriever** — 多信号加权检索

### 提示词组织方式

提示词体系已统一为“配置化 Agent 主提示词 + Python 共享运行时片段 + Tool Schema 描述”三层:

1. **Agent 主提示词**: `config/agents.yaml` 中的 `system_prompt` 是各 Agent 的可编辑主契约。所有 Agent 统一使用以下章节：`角色边界`、`输入变量`、`工具调用规则/工作流程`、`安全与权限约束`、`输出契约`。`output_format=json` 的 Agent 必须明确“严格输出纯 JSON，不输出 markdown”。
2. **共享运行时片段**: `backend/src/core/prompts.py` 集中维护运行时代码拼接的提示词片段，包括长期记忆不可信注入块、token 预算 nudge、对话反思 prompt、内置 Tool 描述。`Agent._build_messages()` 和 `MemoryProcessor._build_messages()` 只能通过这些构建函数拼接动态 prompt，避免各模块文案漂移。
3. **Tool 描述**: 内置 Tool 的 `CapabilitySchema.description` 统一来自 `core.prompts.TOOL_DESCRIPTIONS`。`config/capabilities.yaml` 的 `description` 保持同风格，用于配置展示和动态能力描述；`prompt` 字段仅作为显式覆盖层，仍不得修改 `parameters` JSON Schema。

新增或修改提示词时必须保持字段名与 `input_schema` 一致，变量名使用 snake_case；失败处理统一用 blocked / error / permission_denied / truncated 语义说明，不编造未执行的结果。涉及写入、Shell、联网、记忆注入和外部资料时必须保留安全/权限边界。

### 能力系统

能力系统由 `CapabilityRegistry` 统一管理，Agent、原生 Tool、动态 Tool 都以同一接口暴露。

代码类能力:
- `CodeParserCapability` — AST 代码解析
- `StaticAnalyzerCapability` — 静态代码质量检查
- `TestRunnerCapability` — 测试结构解析

常规助理工具:
- `memory_search`、`datetime_tool`、`calculator`、`web_fetch`
- `file_search`、`read_file`、`write_file`、`json_tool`、`text_processor`
- `bash` 默认关闭，需设置 `ENABLE_SHELL_TOOL=true`；启用后默认在项目根目录 `./workspace` 执行

动态 Tool 支持 `template`、`checklist`、`regex_extract` 三种安全模式，可通过进化中心/API 创建并挂载到 Agent。

Tool 提示词覆盖层只修改 `CapabilitySchema.description`，也就是模型看到的 Tool 说明；`parameters` JSON Schema 只读展示，不通过网页修改，避免破坏工具调用协议。
覆盖层必须保留原 Tool 的执行契约，包括只读标记、并发安全标记、结果大小限制和权限校验钩子。

联网工具 (`web_fetch` / `web_search`) 只允许访问公网 HTTP(S) 目标。请求前和重定向后都要拒绝 loopback、内网、link-local、保留地址和未指定地址，避免 Agent 通过工具访问本机服务、局域网或云 metadata 地址。网络 I/O 必须放到线程或异步 HTTP 客户端中执行，不能阻塞 FastAPI 的事件循环。

### 工作流编排

`WorkflowOrchestrator` 支持顺序/并行执行，工作流模板在 `config/workflows.yaml` 中定义。

当前执行器具备两项关键运行时保障:
- 支持步骤级 `timeout`，单步超时后会返回失败状态，避免工作流或管线无限卡住。
- 支持递归变量解析，`input` 中的 dict / list / tuple 都可以安全引用 `${upstream_output}`。
- 当前 `Pipeline` 是主执行入口；历史 `WorkflowOrchestrator` / `EventEngine` 若在旧分支或兼容测试中保留，调度当前通用 Agent 时必须通过 `Agent.run()` 兼容层执行，不能依赖已移除的旧 `process()` 子类实现。

### 配置管理

配置加载优先级:
1. `config/*.yaml` — 系统与组件主配置
2. `backend/src/config.yaml` — 本地运行时覆盖
3. 环境变量 — 最终覆盖 (LLM_PROVIDER, LLM_API_KEY 等)

默认服务监听 `127.0.0.1`，`bash` 工具默认关闭，需显式设置 `ENABLE_SHELL_TOOL=true` 才启用。所有未显式指定目录的文件工具、bash cwd、Artifact 与任务 transcript 默认使用项目根目录下 `./workspace`。

## 启动流程

```
lifespan() 初始化顺序:
1. load_config() / load_yaml_configs() → 合并 `config/*.yaml`、`backend/src/config.yaml` 与环境变量
2. bus.start()            → 启动 UnifiedBus
3. ContextStore()         → 上下文存储
4. CapabilityRegistry     → 能力系统
5. TriggerRegistry        → 扳机系统
6. EventEngine            → 事件引擎
7. WorkflowOrchestrator   → 工作流编排
8. init_memory_system()   → 记忆系统
9. reload_agent()         → Agent 创建 + 注册
10. lifecycle monitor     → 健康监控
```

所有子系统都有 fallback 机制：config/ 缺失时回退到硬编码默认值。

## 数据流

### 对话流程
```
用户消息 → WebSocket Handler → assistant capability
→ 仅向当前连接返回 assistant_response

Pipeline 执行 → bus.publish(step_started / step_completed)
→ WebSocket 事件桥接 → 广播到监控面板
```

### 任务流水线
```
提交任务 → POST /api/tasks → bus.publish(plan_request)
→ PlannerAgent → bus.publish(plan_created)
→ CoderAgent → bus.publish(code_generated)
→ ReviewerAgent → bus.publish(review_passed/failed)
```

## 进化中心：系统架构仪表盘

进化页面的产品定位是 **Agentic System Architecture Dashboard + Evolution Command Center**。它不再把 assistant、Agent CRUD 或 Tool CRUD 作为“进化”本身，而是先聚合展示当前系统状态：Agents、Tools、Skills/MCP、Memory/Reflection、Models/Providers、Runtime/Pipeline、Evolution Pipeline 和 Observability/Config。

后端通过 `GET /api/evolution/system-status` 复用运行时注册中心、配置、记忆、管线和总线指标生成状态摘要；通过 `POST /api/evolution/command` 将用户目标与当前状态快照合成为可提交给任务管线的进化指令。原有动态 Tool 和 Tool prompt 接口继续作为组件维护能力保留。

---

## v2.5 Agent Run 调度架构

系统默认编排从固定 Pipeline 迁移为 Agent Run。Pipeline 的问题是把步骤顺序写在模板里，适合演示固定 plan/code/review，却不适合多 agent、多 session、多 workspace 并发工作，也不适合让 Agent 根据工具结果自主改变策略。

Agent Run 的核心抽象：

```
RunInstance = {
  run_id/task_id,
  agent_name,
  session_id,
  workspace_id,
  goal,
  mode: autonomous,
  strategy: agent_decides,
  status,
  progress,
  transcript,
  output/error
}
```

调度层职责收敛为：创建实例、分配隔离 workspace、设置 contextvars、启动 Agent tool-use loop、落盘 transcript、广播 monitor 事件、支持取消。它不读取固定步骤、不推断 plan/code/review 顺序，也不把 tool 调用伪装成流水线步骤。

兼容边界：

- `core.pipeline.Pipeline`、`/api/pipelines/*` 和 YAML pipeline 模板保留，用于旧演示与迁移。
- `/api/tasks` 默认 `pipeline=auto` 已映射到 Agent Run；显式 `pipeline=<template>` 才进入旧 Pipeline。
- 前端“运行”页面展示多个并行 Agent Run；“管线(兼容)”页面只服务历史模板。
