# 基于多智能体协作的自动化代码生成与审查系统 — 架构设计文档

**版本**: v2.1 (workflow-timeout 后)
**日期**: 2026-04-23
**作者**: 项目维护者

> 本文档面向后续 AI 和开发者，完整描述系统架构、模块关系和开发规范。
> **所有内容基于实际代码审计，非理论设计。**
>
> 🧠 **记忆层 v2 设计中**：私人助理式全局长期记忆方案见
> `docs/superpowers/specs/2026-04-26-private-assistant-memory-lite-design.md`。
> 新方案不做 session/persona 隔离，重点补齐自动形成、结构化摘要、可解释召回和遗忘巩固。

---

## 1. 项目概况

### 1.1 定位

本科毕业设计项目，实现一个**事件驱动的多智能体协作系统**，支持从需求分析到代码生成再到自动审查的全流程自动化。

### 1.2 核心特性

| 特性 | 实现状态 | 说明 |
|------|----------|------|
| 统一消息总线 (UnifiedBus) | ✅ 已实现 | 优先级队列、消息历史、运行指标、向后兼容 SimpleBus |
| 事件引擎 + 扳机系统 | ✅ 已实现 | ECA 规则引擎，条件评估，优先级调度 |
| 4 个专业智能体 | ✅ 已实现 | Assistant / Planner / Coder / Reviewer |
| 长期记忆系统 | ✅ 已实现 | 情景/语义/程序记忆，InMemory + ChromaDB 双后端 |
| 工作流编排 | ✅ 已实现 | 顺序/并行执行，YAML 模板驱动 |
| 能力插件系统 | ✅ 已实现 | CodeParser + StaticAnalyzer + TestRunner |
| YAML 配置体系 | ✅ 已实现 | config/ 目录 5 个 YAML，动态加载，fallback 机制 |
| 前后端分离 | ✅ 已实现 | FastAPI + React/TypeScript + WebSocket |
| MCP 集成 | ❌ 预留接口 | CapabilityRegistry 预留了 MCP 类型支持 |
| 消息持久化 | ❌ 预留接口 | 当前仅内存队列 |

### 1.3 项目统计

| 指标 | 数值 |
|------|------|
| Python 源文件 | 62 个 |
| 前端 TS/TSX 文件 | 15 个 |
| 前端 CSS 文件 | 10 个 |
| 后端代码行数 | ~8,300 行 |
| 前端代码行数 | ~5,100 行 (TS+CSS) |
| 测试用例 | ~331 个 (12 个测试文件) |
| 测试代码行数 | ~4,900 行 |
| YAML 配置文件 | 5 个 (config/) + 1 个 (src/config.yaml) |

---

## 2. 目录结构 (实际)

```
agentic-system/
├── AGENTS.md                           # ← 你正在读的文档
├── README.md                           # 面向用户/评审的说明
├── QUICKSTART.md                       # 5 分钟快速上手
├── PROGRESS.md                         # 开发进度追踪
├── HANDOFF.md                          # 交接文档
├── pyproject.toml                      # Python 项目元数据
├── requirements.txt                    # 顶层依赖 (指向 backend/)
├── example_simple.py                   # 独立演示脚本
│
├── config/                             # ★ YAML 配置目录 (被 config.py 动态加载)
│   ├── agents.yaml                     #   智能体定义
│   ├── triggers.yaml                   #   扳机规则
│   ├── workflows.yaml                  #   工作流模板
│   ├── capabilities.yaml               #   能力插件
│   └── system.yaml                     #   全局系统配置 (LLM/Bus/Memory 等)
│
├── backend/
│   ├── requirements.txt                # Python 依赖清单
│   ├── config.example.yaml             # config.yaml 模板
│   ├── config/                         # 旧版配置副本 (主配置已在根目录 config/)
│   │   └── *.yaml
│   ├── src/
│   │   ├── config.yaml                 # ★ 运行时 LLM 配置 (api_key 等)
│   │   ├── config.yaml.example         # config.yaml 模板
│   │   │
│   │   ├── agents/                     # 智能体实现 (4 个)
│   │   │   ├── __init__.py
│   │   │   ├── assistant.py            #   对话助手 (LLM + 记忆检索)
│   │   │   ├── planner.py              #   任务规划 (需求 → 子任务计划)
│   │   │   ├── coder.py                #   代码生成 (结构化 JSON 输出)
│   │   │   └── reviewer.py             #   代码审查 (六维度评估)
│   │   │
│   │   ├── api/                        # FastAPI 应用
│   │   │   ├── main.py                 #   ★ 应用入口 (lifespan + 动态加载)
│   │   │   ├── dependencies.py         #   依赖注入 (全局状态容器)
│   │   │   ├── schemas.py              #   Pydantic 请求/响应 Schema
│   │   │   ├── routes/                 #   路由模块 (5 个)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agents.py           #     GET/POST /api/agents/*
│   │   │   │   ├── tasks.py            #     GET/POST/DELETE /api/tasks/*
│   │   │   │   ├── workflows.py        #     GET/POST /api/workflows/*
│   │   │   │   ├── memory.py           #     GET/POST/DELETE /api/memory/*
│   │   │   │   └── config.py           #     GET/POST /api/config + /api/health
│   │   │   └── websocket/
│   │   │       ├── __init__.py
│   │   │       └── handlers.py         #   WebSocket 连接管理 + 定向回复/监控广播
│   │   │
│   │   ├── core/                       # 核心框架
│   │   │   ├── config.py               #   ★ 配置管理 (load_config + load_yaml_configs)
│   │   │   ├── agent/                  #   智能体框架
│   │   │   │   ├── base.py             #     BaseAgent 抽象基类
│   │   │   │   ├── registry.py         #     AgentRegistry 注册中心
│   │   │   │   └── lifecycle.py        #     AgentLifecycleManager
│   │   │   ├── bus/                    #   消息总线
│   │   │   │   ├── types.py            #     Event/Message/Request/Response
│   │   │   │   ├── simple_bus.py       #     SimpleBus (旧版，保留兼容)
│   │   │   │   ├── unified_bus.py      #     ★ UnifiedBus (当前使用)
│   │   │   │   ├── channels.py         #     Event/Request/Broadcast Channel
│   │   │   │   └── router.py           #     MessageRouter
│   │   │   ├── event/                  #   事件引擎
│   │   │   │   ├── engine.py           #     EventEngine
│   │   │   │   ├── trigger.py          #     Trigger 数据类
│   │   │   │   └── registry.py         #     TriggerRegistry
│   │   │   ├── memory/                 #   记忆系统
│   │   │   │   ├── types.py            #     Memory/MemoryType
│   │   │   │   ├── store.py            #     InMemoryStore + ChromaStore
│   │   │   │   ├── embedding.py        #     向量嵌入 (OpenAI)
│   │   │   │   ├── retriever.py        #     MemoryRetriever
│   │   │   │   └── formation.py        #     MemoryFormation
│   │   │   ├── capability/             #   能力系统
│   │   │   │   ├── base.py             #     CapabilityBase 抽象
│   │   │   │   ├── native.py           #     ★ 内置能力 (3 个)
│   │   │   │   └── registry.py         #     CapabilityRegistry
│   │   │   ├── context/store.py        #   上下文管理 (三层作用域)
│   │   │   ├── workflow/               #   工作流编排
│   │   │   │   ├── orchestrator.py     #     WorkflowOrchestrator
│   │   │   │   └── types.py            #     Task/TaskResult/WorkflowResult
│   │   │   └── llm/                    #   LLM 客户端
│   │   │       ├── base.py / factory.py
│   │   │       ├── openai_client.py
│   │   │       └── anthropic_client.py
│   │   │
│   │   ├── capabilities/builtin/      # 独立能力实现 (完整版)
│   │   │   ├── code_parser.py
│   │   │   ├── static_analyzer.py
│   │   │   └── test_runner.py
│   │   │
│   │   └── utils/                     # 工具 (logger.py + tracer.py)
│   │
│   └── tests/                         # 测试 (12 个文件, ~331 用例)
│       ├── unit/ (10 个)
│       └── integration/ (2 个)
│
├── frontend/                          # React + TypeScript + Vite
│   └── src/
│       ├── components/ (8 个面板)
│       ├── hooks/useWebSocket.ts
│       ├── store/appStore.tsx
│       ├── api/client.ts
│       ├── types/index.ts
│       ├── App.tsx + main.tsx
│       └── *.css
│
├── docs/                              # 项目文档
│   ├── architecture.md
│   ├── api.md
│   ├── bus-design.md
│   └── deployment.md
│
└── examples/                          # 示例目录
```

---

## 3. 核心架构

### 3.1 系统分层

```
用户界面 (React SPA)
    │ HTTP REST + WebSocket
    ▼
应用层 (FastAPI + Routes + WebSocket handlers)
    │
    ▼
消息总线层 (UnifiedBus — 系统神经中枢)
    │         │         │         │
    ▼         ▼         ▼         ▼
事件引擎   记忆系统   上下文管理   能力注册中心
    │
    ▼
智能体层 (4 个 Agent，通过 AgentRegistry 管理)
    │
    ▼
LLM 客户端层 (OpenAI / Anthropic)
```

### 3.2 启动流程 (main.py lifespan)

`main.py` 的 `lifespan()` 函数按以下顺序初始化所有子系统:

```
1. load_config() + load_yaml_configs() → 合并 config/*.yaml、backend/src/config.yaml 和环境变量
2. bus.start()                  → 启动 UnifiedBus (优先级队列处理循环)
3. ContextStore()               → 初始化上下文存储
4. CapabilityRegistry           → 从 config/capabilities.yaml 加载能力
5. TriggerRegistry              → 从 config/triggers.yaml 加载扳机
6. EventEngine                  → 初始化事件引擎
7. WorkflowOrchestrator         → 从 config/workflows.yaml 加载模板
8. init_memory_system()         → 初始化记忆存储/检索/巩固
9. reload_agent()               → 从 config/agents.yaml 创建并注册 Agent
10. lifecycle_manager.start()   → 启动健康监控
```

**关键设计: 所有子系统都有 fallback 机制。** 如果 `config/*.yaml` 缺失或为空，回退到硬编码默认值。

### 3.3 消息总线 (UnifiedBus)

位于 `core/bus/unified_bus.py`，是系统的通信中枢。

**通信模式:**

| 模式 | 方法 | 说明 |
|------|------|------|
| 发布/订阅 | `publish()` / `subscribe()` | 事件驱动，一对多 |
| 请求/响应 | `request()` / `handle_request()` | 同步调用，一对一 |
| 点对点 | `send()` / `register_route()` | 路由分发 |
| 广播 | `broadcast()` / `register_broadcast_receiver()` | 全局通知 |

**内部组件:**
- `EventChannel` — 事件订阅和分发
- `RequestChannel` — 请求/响应对管理
- `BroadcastChannel` — 广播接收器
- `MessageRouter` — 路由匹配 (支持 * 和 # 通配)
- `asyncio.PriorityQueue` — 优先级消息队列
- `deque` — 消息历史
- `BusMetrics` — 运行指标

**向后兼容:** 通过 `_subscribers` 字典兼容旧版 SimpleBus 接口。

### 3.4 事件引擎与扳机系统

**EventEngine** (`core/event/engine.py`):
1. 接收总线事件
2. 在 TriggerRegistry 中查找匹配的扳机 (按优先级排序)
3. 安全评估条件表达式 (`eval` with restricted `__builtins__`)
4. 调度 Agent: 同步扳机串行执行，异步扳机并发执行

**Trigger 字段:**
- `id` — 唯一标识
- `event_type` — 监听的事件类型
- `agent_name` — 响应的 Agent
- `condition` — Python 条件表达式 (可选)
- `priority` — 优先级 (0 最高)
- `async_mode` — 异步执行 (默认 True)
- `enabled` — 是否启用

### 3.5 Agent 系统

**BaseAgent** (`core/agent/base.py`):
- `process(data)` — 核心处理 (子类必须实现)
- `on_event(event)` — 事件处理入口 (可选重写)
- `emit(event_type, data)` — 发射事件到总线
- `get_metadata()` — 返回元数据

**4 个实现:**

| Agent | 输入 | 输出 | 发射事件 |
|-------|------|------|----------|
| AssistantAgent | user_message | LLM 回复 + 记忆上下文 | assistant_completed |
| PlannerAgent | requirement | 结构化子任务计划 (JSON) | plan_created |
| CoderAgent | task/plan | 代码 + 文件路径 + 说明 (JSON) | code_generated |
| ReviewerAgent | code | 六维度审查报告 (JSON) | review_passed / review_failed |

**标准事件链:**
```
user_message → WebSocket handler → Assistant capability → 定向返回当前连接
pipeline step_started/step_completed → UnifiedBus → WebSocket 广播 → MonitorPanel
plan_request → Planner → plan_created → Coder → code_generated → Reviewer → review_passed/failed
```

### 3.6 记忆系统

**三种类型:** episodic (情景) / semantic (语义) / procedural (程序)

**v2 方向:** 升级为私人助理式全局长期记忆层。所有记忆默认进入共享个人记忆池，`session_id` 仅作为来源追踪，不作为默认召回过滤条件；自动对话反思缓冲必须按 `session_id` 隔离，避免跨会话混合摘要。新增自动对话反思、`canonical_summary` / `assistant_context` 双摘要、检索评分解释和近似去重。

**安全约束:** 记忆注入 Agent prompt 时必须标记为不可信资料，只能作为事实参考，不能执行记忆文本中的指令。解释性召回必须先使用底层 `MemoryStore.search()` 做候选粗筛，保留 ChromaDB 等后端的语义检索能力；只有最终选中的召回结果更新访问记录。

**组件:**
| 组件 | 职责 |
|------|------|
| `MemoryStore` | 存储后端 (InMemoryStore 或 ChromaStore) |
| `MemoryFormation` | 创建、巩固 (去重合并)、遗忘 (时间衰减) |
| `MemoryRetriever` | 多信号加权检索 (相关性 + 时间 + 重要性 + 频率) |
| `embedding.py` | OpenAI text-embedding 向量化 |

### 3.7 能力系统

**内置能力** (在 `core/capability/native.py`):

| 能力 | 功能 |
|------|------|
| `CodeParserCapability` | Python AST 解析，提取函数/类/导入 |
| `StaticAnalyzerCapability` | 行长度、函数长度、未使用导入检查 |
| `TestRunnerCapability` | 代码测试执行 |

> **注意:** `capabilities/builtin/` 下也有独立的完整实现。`core/capability/native.py` 是简化版，被 main.py 直接使用。

### 3.8 工作流编排

`WorkflowOrchestrator` 支持:
- 顺序执行 (`execute_sequential`)
- 并行执行 (`execute_parallel`)
- YAML 模板驱动 (从 `config/workflows.yaml` 加载)
- 步骤级超时控制 (`timeout` 字段，超时后标记失败并终止后续顺序步骤)
- 嵌套变量解析 (支持 dict / list / tuple 中的 `${var}` 引用)

预定义工作流:
1. `code_generation_and_review` — 规划 → 编码 → 审查 → 条件修复
2. `task_decompose_and_execute` — 分解 → 编码
3. `full_pipeline` — 规划 → 编码 → 审查 → 修复 → 再审查

---

## 4. 配置管理

### 4.1 两层配置

| 配置 | 路径 | 用途 | 加载函数 |
|------|------|------|----------|
| 运行时配置 | `backend/src/config.yaml` | 本地运行时覆盖 (建议不入库保存密钥) | `load_config()` |
| 组件配置 | `config/*.yaml` (项目根目录) | 系统与组件主配置 | `load_yaml_configs()` |

### 4.2 config/ 目录详解

| 文件 | 顶层键 | 作用 |
|------|--------|------|
| `system.yaml` | 直接合并到顶层 | 全局配置 (LLM/Bus/Memory/Server 等) |
| `agents.yaml` | `agents` (列表) | 4 个 Agent 定义 |
| `triggers.yaml` | `triggers` (列表) | 5 个事件扳机规则 |
| `capabilities.yaml` | `capabilities` (列表) | 2 个原生能力 (MCP/OpenAPI 预留) |
| `workflows.yaml` | `workflows` (字典) | 3 个工作流模板 |

### 4.3 加载机制

```python
# config.py 中的三个加载函数:
load_config()           # 合并 config/*.yaml + src/config.yaml + 环境变量
load_yaml_configs()     # 加载 config/ 目录 + 深度合并 + 按文件名分键
load_system_config()    # 类型安全版，返回 Pydantic SystemConfig
```

**环境变量覆盖:**
`LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`,
`MEMORY_BACKEND`, `MEMORY_PERSIST_DIR`, `BUS_QUEUE_SIZE`, `BUS_HISTORY_SIZE`

### 4.4 动态加载 (main.py)

使用**类型映射表**将 YAML 中的字符串映射到 Python 类:

```python
_AGENT_CLASS_MAP = {
    "agents.assistant.AssistantAgent": AssistantAgent,
    "assistant": AssistantAgent,  # 兼容短名
    ...
}
_CAPABILITY_CLASS_MAP = {
    "core.capability.native.CodeParserCapability": CodeParserCapability,
    "code_parser": CodeParserCapability,  # 兼容短名
    ...
}
```

---

## 5. API 端点

### 5.1 REST API (19 个端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 获取配置 (隐藏 api_key) |
| POST | `/api/config` | 更新配置 + 热重载 |
| GET | `/api/agents` | 列出所有 Agent |
| GET | `/api/agents/{name}` | 获取 Agent 详情 |
| POST | `/api/agents/{name}/invoke` | 直接调用 Agent |
| POST | `/api/tasks` | 提交新任务 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{task_id}` | 获取任务详情 |
| DELETE | `/api/tasks/{task_id}` | 取消任务 |
| GET | `/api/workflows/templates` | 获取工作流模板 |
| POST | `/api/workflows/execute` | 执行工作流 |
| GET | `/api/memory/stats` | 记忆统计 |
| GET | `/api/memory/list` | 列出记忆 |
| POST | `/api/memory/search` | 搜索记忆 |
| POST | `/api/memory/create` | 创建记忆 |
| DELETE | `/api/memory/{memory_id}` | 删除记忆 |
| POST | `/api/memory/consolidate` | 记忆巩固 |
| POST | `/api/memory/forget` | 记忆遗忘 |

### 5.2 WebSocket

`ws://localhost:8001/ws` — 实时通信。聊天回复仅回当前连接，系统监控事件单独广播。

---

## 6. 前端架构

**技术栈:** React 18 + TypeScript 5 + Vite 5 (无第三方 UI 库)

**状态管理:** `useReducer` + React Context (`AppProvider`)

**8 个面板组件:**

| 组件 | 功能 |
|------|------|
| `Sidebar` | 侧边栏导航 |
| `ChatPanel` | 聊天对话 (用户/AI 消息气泡，记忆使用指示) |
| `AgentPanel` | Agent 状态查看、直接调用 |
| `TaskPanel` | 任务提交、列表、状态跟踪 |
| `WorkflowPanel` | 工作流模板选择、执行 |
| `MemoryPanel` | 记忆统计/列表/搜索/创建/删除 |
| `MonitorPanel` | 系统监控 (连接状态、事件流) |
| `Settings` | LLM 配置面板 (热重载) |

---

## 7. 实现路线图

### Phase 1: 核心基础设施 ✅
- [x] 项目结构搭建 (前后端分离)
- [x] 统一消息总线 (UnifiedBus: 优先级队列 + 消息历史 + 指标)
- [x] 事件引擎和扳机系统 (ECA 规则)
- [x] 配置管理 (YAML + 环境变量 + Pydantic 类型安全)
- [x] 日志和追踪系统

### Phase 2: 智能体系统 ✅
- [x] BaseAgent 抽象基类 (双模式: 事件驱动 + 主动调用)
- [x] AgentRegistry + AgentLifecycleManager
- [x] LLM 客户端 (OpenAI + Anthropic)
- [x] AssistantAgent (对话 + 记忆检索)

### Phase 3: 前后端集成 ✅
- [x] FastAPI 应用 (路由拆分 + 依赖注入)
- [x] WebSocket 实时通信 (连接管理 + 广播)
- [x] React + TypeScript 前端 (8 个面板)
- [x] 配置 API + 热重载

### Phase 4: 记忆系统 ✅
- [x] 记忆存储 (InMemory + ChromaDB 双后端)
- [x] 向量检索 (ChromaDB + 关键词后备)
- [x] 记忆形成和巩固 (创建/去重/合并)
- [x] 记忆遗忘 (时间衰减 + 重要性阈值)
- [x] 记忆检索器 (多信号加权)
- [x] 记忆 REST API + 前端面板

### Phase 5: 基础智能体 ✅
- [x] PlannerAgent (任务分解，结构化计划，重试)
- [x] CoderAgent (代码生成，结构化输出，JSON 容错)
- [x] ReviewerAgent (六维度审查，结构化报告)
- [x] 能力插件 (CodeParser / StaticAnalyzer / TestRunner)

### Phase 6: 高级特性 ✅
- [x] 上下文管理 (三层作用域 ContextStore)
- [x] 错误处理和重试
- [x] 事件引擎 + 扳机系统
- [x] 能力系统 + 注册中心
- [x] 工作流编排 (顺序/并行/条件/重试)
- [x] UnifiedBus 替换 SimpleBus
- [x] YAML 配置体系 (5 个配置文件)
- [x] 前端 TaskPanel + WorkflowPanel
- [ ] MCP 客户端集成 (预留接口)
- [ ] 消息持久化 (预留接口)

### Phase 7: 测试与文档 ✅
- [x] 单元测试 (10 个模块)
- [x] 集成测试 (Agent 流水线 + API 端点)
- [x] 总计 ~331 个测试用例 (12 个测试文件)
- [x] 文档完善 (AGENTS.md / README / QUICKSTART / docs/)
- [ ] 性能优化 (预留)

---

## 8. 开发规范

### 8.1 开发铁律

**所有新功能/改动必须遵循此流程:**

```
1. 📝 先扩充文档 — 在 AGENTS.md 或相关文档中描述功能设计
2. 🔧 按文档编码 — 严格按照文档规范去实现代码
3. ✅ 可行性验收 — 测试通过 + 实际能运行
```

### 8.2 文档同步规则

- 架构变动 → 更新 AGENTS.md + docs/architecture.md
- API 变更 → 更新 docs/api.md
- 配置变更 → 更新 config/ 中的注释 + AGENTS.md §4
- 目录结构变化 → 用 `find` 命令验证后更新 AGENTS.md §2

### 8.3 代码风格

- Python: PEP 8 + 类型注解 + Google 风格 docstring
- TypeScript: 严格模式 + 函数式组件
- 异步: 全面使用 `async/await`
- 提交: `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`

### 8.4 最小化原则

- 只写必要的代码
- 先让功能跑起来，再优化
- 不为未来需求过度设计

---

## 9. 技术栈

### 后端

| 组件 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | ≥ 0.100 |
| ASGI 服务器 | Uvicorn | ≥ 0.20 |
| 数据验证 | Pydantic | ≥ 2.0 |
| LLM - OpenAI | openai SDK | ≥ 1.0 |
| LLM - Anthropic | anthropic SDK | ≥ 0.20 |
| 配置管理 | PyYAML | ≥ 6.0 |
| 日志 | structlog | ≥ 23.0 |
| 向量数据库 | ChromaDB | 可选 |
| 测试 | pytest + pytest-asyncio | ≥ 8.0 |
| HTTP 测试 | httpx | ≥ 0.25 |
| 运行时 | Python | 3.10+ |

### 前端

| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | React | 18.x |
| 语言 | TypeScript | 5.3+ |
| 构建 | Vite | 5.x |
| 运行时 | Node.js | 18+ |

---

## 10. 关键设计决策

### 10.1 为什么使用 UnifiedBus 而非直接调用?
- 解耦智能体依赖
- 支持异步通信和事件驱动
- 便于追踪和调试 (消息历史 + 指标)
- 易于扩展到分布式架构

### 10.2 为什么 YAML 配置而非代码定义?
- 非开发人员也能修改
- 支持热重载
- 易于版本控制和对比
- 降低系统耦合

### 10.3 为什么有 fallback 机制?
- 保证系统在配置不完整时仍能启动
- 降低新开发者的上手门槛
- 便于测试 (不需要完整配置文件)

### 10.4 两套能力实现的说明
- `core/capability/native.py` — 简化版，被 main.py 直接导入使用
- `capabilities/builtin/` — 完整独立版本，包含更丰富的功能
- 两者接口兼容，未来可统一

---

## 附录: 常用命令速查

```bash
# 启动后端
cd backend/src && python -m api.main
# 或
cd backend/src && uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload

# 启动前端
cd frontend && npm install && npm run dev

# 运行测试
python3 -m pytest backend/tests/ -q
python3 -m pytest backend/tests/unit/ -v
python3 -m pytest backend/tests/integration/ -v

# 项目统计
find backend/src -name "*.py" | grep -v __pycache__ | wc -l
find backend/src -name "*.py" | grep -v __pycache__ | xargs wc -l | tail -1

# 文件树
find . -type f -name "*.py" -o -name "*.ts" -o -name "*.tsx" | grep -v node_modules | grep -v __pycache__ | sort
```

---

**文档状态**: v2.1 — 基于实际代码审计
**最后更新**: 2026-04-23
