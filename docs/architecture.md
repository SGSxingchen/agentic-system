# 系统架构

> 最后更新: 2026-04-26 | 与 CLAUDE.md 保持一致
>
> ⚠️ **编排层 v2 设计中**：本文档描述的是 v1 实现现状。新版编排层
> （反应式 Agent 工具循环 + Task 抽象 + 子 Agent 派生 + Stop Hooks）
> 见 [`./orchestrator-v2.md`](./orchestrator-v2.md)。落实后本文档将重写
> "编排" 与 "数据流 / 任务流水线" 章节。
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

v2 方向: 记忆系统将升级为私人助理式全局长期记忆层。所有记忆默认进入共享个人记忆池，`session_id` 仅作为来源追踪；新增自动对话反思、`canonical_summary` / `assistant_context` 双摘要、检索评分解释和近似去重。

组件:
- **MemoryStore** — InMemoryStore 或 ChromaStore
- **MemoryFormation** — 创建 / 巩固 (去重) / 遗忘 (衰减)
- **MemoryRetriever** — 多信号加权检索

### 能力系统

能力系统由 `CapabilityRegistry` 统一管理，Agent、原生 Tool、动态 Tool 都以同一接口暴露。

代码类能力:
- `CodeParserCapability` — AST 代码解析
- `StaticAnalyzerCapability` — 静态代码质量检查
- `TestRunnerCapability` — 测试结构解析

常规助理工具:
- `memory_search`、`datetime_tool`、`calculator`、`web_fetch`
- `file_search`、`read_file`、`write_file`、`json_tool`、`text_processor`
- `bash` 默认关闭，需设置 `ENABLE_SHELL_TOOL=true`

动态 Tool 支持 `template`、`checklist`、`regex_extract` 三种安全模式，可通过进化中心/API 创建并挂载到 Agent。

Tool 提示词覆盖层只修改 `CapabilitySchema.description`，也就是模型看到的 Tool 说明；`parameters` JSON Schema 只读展示，不通过网页修改，避免破坏工具调用协议。

### 工作流编排

`WorkflowOrchestrator` 支持顺序/并行执行，工作流模板在 `config/workflows.yaml` 中定义。

当前执行器具备两项关键运行时保障:
- 支持步骤级 `timeout`，单步超时后会返回失败状态，避免工作流或管线无限卡住。
- 支持递归变量解析，`input` 中的 dict / list / tuple 都可以安全引用 `${upstream_output}`。

### 配置管理

配置加载优先级:
1. `config/*.yaml` — 系统与组件主配置
2. `backend/src/config.yaml` — 本地运行时覆盖
3. 环境变量 — 最终覆盖 (LLM_PROVIDER, LLM_API_KEY 等)

默认服务监听 `127.0.0.1`，`bash` 工具默认关闭，需显式设置 `ENABLE_SHELL_TOOL=true` 才启用。

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
