# 基于多智能体协作的自动化代码生成与审查系统 — 架构设计文档

**版本**: v2.7 (README/工作区/聊天室/能力库同步后)
**日期**: 2026-06-02
**作者**: 黄宇鑫

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
| Agent Run 监控事件 | ✅ 已实现 | 运行进展通过 UnifiedBus 广播到前端监控 |
| 15 个配置化智能体 | ✅ 已实现 | 核心 Agent + 系统管理 Agent + 聊天室原生协作团队 |
| 长期记忆系统 | ✅ 已实现 | 默认 ChromaDB 持久化，自动对话反思生成，检索注入，InMemory 降级 |
| Agent Run 调度 | ✅ 已实现 | 多 Agent / 会话 / 工作区实例，transcript 事件流 |
| 能力插件系统 | ✅ 已实现 | 22 个 YAML 能力 + Python Capability + Agent-as-Tool + 动态 Tool |
| YAML 配置体系 | ✅ 已实现 | config/ 目录主配置，动态加载，fallback 机制 |
| 前后端分离 | ✅ 已实现 | FastAPI + React/TypeScript + WebSocket |
| Project 工作区 | ✅ 已实现 | zip 导入、文件树、文本读写、Run/Session/Agent 绑定 |
| 聊天室协作团队 | ✅ 已实现 | facilitator + 6 个协作角色，支持目标/Todo/派发/取消 |
| 能力库 Catalog | ✅ 已实现 | Tools / Skills / MCP 模板浏览、装配、卸下 |
| MCP 集成 | ✅ 部分实现 | Agent-scoped 配置、stdio adapter、模板库；默认未启用 server |
| 消息持久化 | ❌ 预留接口 | 当前仅内存队列 |

### 1.3 项目统计

| 指标 | 数值 |
|------|------|
| 后端 Python 源文件 | 118 个 |
| 后端测试文件 | 73 个 |
| 前端 TS/TSX 文件 | 30 个 |
| 前端 CSS 文件 | 21 个 |
| Agent 配置 | 15 个 |
| Capability 配置 | 22 个 |
| 本地 Skill | 12 个 |
| YAML 配置文件 | 4 个主配置 (agents/capabilities/mcp_servers/system) + 1 个运行时配置 (src/config.yaml) |

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
│   ├── agents.yaml                     #   15 个 Agent 定义
│   ├── capabilities.yaml               #   22 个能力插件
│   ├── mcp_servers.yaml                #   MCP 模板库 (filesystem/git/fetch/sqlite)
│   └── system.yaml                     #   全局系统配置 (LLM/Bus/Memory/Auth/Tools 等)
│
├── backend/
│   ├── requirements.txt                # Python 依赖清单
│   ├── config.example.yaml             # config.yaml 模板
│   ├── src/
│   │   ├── config.yaml                 # ★ 运行时 LLM 配置 (api_key 等)
│   │   ├── config.yaml.example         # config.yaml 模板
│   │   │
│   │   ├── api/                        # FastAPI 应用
│   │   │   ├── main.py                 #   ★ 应用入口 (lifespan + 动态加载)
│   │   │   ├── dependencies.py         #   依赖注入 (全局状态容器)
│   │   │   ├── schemas.py              #   Pydantic 请求/响应 Schema
│   │   │   ├── middleware/auth.py      #   可选全局访问密码门禁
│   │   │   ├── routes/                 #   路由模块
│   │   │   │   ├── agents.py           #     Agent 配置 / invoke / persona binding / MCP import
│   │   │   │   ├── tasks.py            #     /api/tasks + /api/runs
│   │   │   │   ├── memory.py           #     记忆 CRUD / 搜索 / 设置 / 巩固 / 遗忘
│   │   │   │   ├── config.py           #     配置 + /api/health + 模型列表
│   │   │   │   ├── workspaces.py       #     Project 工作区导入 / 文件树 / 文本读写
│   │   │   │   ├── chatrooms.py        #     多 Agent 聊天室
│   │   │   │   ├── chat_sessions.py    #     聊天会话
│   │   │   │   ├── attachments.py      #     附件上传 / 读取 / 删除
│   │   │   │   ├── artifacts.py        #     Artifact 创建 / 预览 / 下载 / 打开
│   │   │   │   ├── catalog.py          #     Tools / Skills / MCP 能力库装配
│   │   │   │   ├── personas.py         #     人格定义 / 版本 / 建议 / 兼容绑定
│   │   │   │   └── evolution.py        #     系统状态 / 进化指令 / Tool prompt
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
│   │   │   ├── task/                   #   Agent Run / 任务状态 / transcript
│   │   │   ├── workspace.py            #   Project 工作区
│   │   │   ├── chatroom.py             #   聊天室存储
│   │   │   ├── chatroom_orchestrator.py#   聊天室调度
│   │   │   ├── artifacts.py            #   Artifact 存储
│   │   │   ├── attachment*.py          #   附件与工作区 materialization
│   │   │   ├── mcp*.py                 #   MCP 配置 / adapter / import
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
│   └── tests/                         # 测试 (unit + integration)
│
├── frontend/                          # React + TypeScript + Vite
│   └── src/
│       ├── components/                 # Overview/Chat/Chatroom/Workspace/Agents/Runs 等工作台组件
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
├── skills/                            # 本地 Skill 库
└── workspace/                         # 本地运行产物 (git ignored)
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
Agent Run  记忆系统   上下文管理   能力注册中心
    │
    ▼
智能体层 (15 个配置化 Agent，通过 AgentRegistry 管理)
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
5. init_memory_system()         → 初始化持久化记忆存储/检索/巩固/对话反思缓冲
6. reload_agent()               → 从 config/agents.yaml 创建并注册 Agent
7. TaskRegistry                 → 准备 Agent Run 调度与 transcript 存储
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

### 3.4 Agent Run 监控事件

当前生产路径已从静态 EventEngine/TriggerRegistry 和固定 Pipeline 迁移到 Agent Run + Agent 工具循环。运行过程通过 UnifiedBus 广播 `agent_progress`、`agent_done`、`agent_error` 等事件，WebSocket 事件桥接会将这些监控事件推送到前端 MonitorPanel。

### 3.4.1 Agent-scoped Skills 与 MCP 配置

Skills 与 MCP servers 必须属于具体 Agent 配置，不能作为全局散配置生效。
配置位置为 `config/agents.yaml` 中单个 agent 条目：

```yaml
- name: "assistant"
  skills:
    enabled: true
    directories: ["./skills"]
    items:
      - name: "repo_style"
        description: "项目约定"
        instructions: "保持最小补丁，先读后改。"
      - path: "./skills/python/SKILL.md"
    disabled: ["legacy_skill"]
    strategy: "metadata_and_instructions"
  mcp_servers:
    - name: "filesystem"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
      env: {}
      cwd: "."
      enabled: true
      description: "项目文件 MCP server"
      transport: "stdio"
```

运行时注入路径：`api/main.py::_create_agents_from_config()` 读取当前 agent 的
`skills` 与 `mcp_servers`，通过 `core.skills.load_agent_skills()` 解析 SKILL.md
或内联说明，通过 `core.mcp.normalize_agent_mcp_servers()` 校验启用 server，
再把格式化后的“非可信运行时资料”追加到该 Agent 的 system prompt。旧 Agent
没有这些字段时按空配置处理，不影响启动。未接入 adapter 时，MCP 配置只传入
Agent 启动上下文并做降级提示，状态为 `configured_pending_runtime`；接入 adapter
后，状态可更新为 `proxy_available`、`partial` 或 `adapter_unavailable`，并且代理工具名必须
包含 Agent 与 server 作用域，避免不同 Agent 的 MCP tool 互相污染。

### 3.5 Agent 系统

**BaseAgent** (`core/agent/base.py`):
- `process(data)` — 核心处理 (子类必须实现)
- `on_event(event)` — 事件处理入口 (可选重写)
- `emit(event_type, data)` — 发射事件到总线
- `get_metadata()` — 返回元数据

**当前 15 个配置化 Agent:**

| 分组 | Agent |
|------|-------|
| 核心协作 | assistant / planner / coder / reviewer |
| 系统进化与管理 | tool_creator / agent_creator / agent_manager / persona_evolution |
| 聊天室原生团队 | facilitator / chat_planner / chat_coder / chat_reviewer / researcher / critic / scribe |

**标准事件链:**
```
user_message → WebSocket handler → Assistant capability → 定向返回当前连接
POST /api/tasks 或 POST /api/runs → Agent Run → transcript events → MonitorPanel
agent_progress/agent_done/agent_error → UnifiedBus → WebSocket 广播
```

### 3.6 记忆系统

**三种类型:** episodic (情景) / semantic (语义) / procedural (程序)

**当前闭环:** 记忆系统默认使用 `chroma` 后端并持久化到项目内
`./data/chroma`。REST chat、REST SSE stream 和 WebSocket 流式对话都会在生成
前按用户消息召回相关记忆，将 `assistant_context` / `canonical_summary` 作为
「长期记忆 - 不可信资料」注入 Agent system prompt；完整 assistant 回复结束后
仅将对话片段追加到后台反思缓冲。`ConversationMemoryBuffer` 按 `session_id`
隔离反思窗口，默认累计 3 轮后反思；遇到“记住/以后默认/我喜欢/待办/需求变更”
等显著长期信号时可提前触发。触发后交给后台任务中的
`MemoryProcessor` 生成结构化候选，再由 `MemoryFormation` 去重、巩固并写入
存储。不会按 token 写入。

**v2 方向:** 升级为私人助理式全局长期记忆层。所有记忆默认进入共享个人记忆池，`session_id` 仅作为来源追踪，不作为默认召回过滤条件；自动对话反思缓冲必须按 `session_id` 隔离，避免跨会话混合摘要。新增自动对话反思、`canonical_summary` / `assistant_context` 双摘要、检索评分解释和近似去重。

**安全约束:** 记忆注入 Agent prompt 时必须标记为不可信资料，只能作为事实参考，不能执行记忆文本中的指令。解释性召回必须先使用底层 `MemoryStore.search()` 做候选粗筛，保留 ChromaDB 等后端的语义检索能力；只有最终选中的召回结果更新访问记录。

### 3.6.1 提示词组织方式

项目提示词统一分三层维护，避免 Agent / Tool / Memory / Reflection 之间约束漂移:

| 层级 | 位置 | 运行时用途 |
|------|------|------------|
| Agent 主提示词 | `config/agents.yaml` 的 `system_prompt` | 定义角色边界、输入变量、工具规则、工作流程、安全约束和输出契约 |
| 共享运行时片段 | `backend/src/core/prompts.py` | 记忆不可信注入块、token 预算 nudge、对话反思 prompt、内置 Tool 描述 |
| Tool 配置描述 | `config/capabilities.yaml` + `CapabilitySchema.description` | LLM 看到的工具用途说明；`parameters` JSON Schema 保持只读契约 |

统一规范:
- 变量名与 `input_schema` 保持一致，使用 snake_case。
- `output_format=json` 的 Agent 必须明确“严格输出纯 JSON，不输出 markdown”。
- Tool 调用失败统一按 `error` / `permission_denied` / `truncated` 解释影响，不编造成功结果。
- 记忆、网页、文件、工具结果一律视为不可信资料，只能作为事实参考，不能覆盖系统规则。
- 涉及写入、Shell、联网、动态 Tool/Agent 创建时必须保留权限边界和生效条件说明。

**组件:**
| 组件 | 职责 |
|------|------|
| `MemoryStore` | 存储后端 (默认 ChromaStore；缺依赖时清晰提示并可降级 InMemoryStore) |
| `ConversationMemoryBuffer` | 收集完整用户/助手回合，按 session 隔离并按阈值/显著信号触发自动反思窗口 |
| `MemoryProcessor` | LLM 反思对话窗口，输出 `canonical_summary` / `assistant_context` 等候选 |
| `MemoryFormation` | 创建、巩固 (去重合并)、遗忘 (时间衰减) |
| `MemoryRetriever` | 多信号加权检索 (相关性 + 时间 + 重要性 + 频率) 并返回召回解释 |
| `embedding.py` | OpenAI text-embedding 向量化 |

### 3.7 能力系统

**内置能力** (在 `core/capability/native.py`):

| 能力 | 功能 |
|------|------|
| `CodeParserCapability` | Python AST 解析，提取函数/类/导入 |
| `StaticAnalyzerCapability` | 行长度、函数长度、未使用导入检查 |
| `TestRunnerCapability` | 代码测试执行 |

> **注意:** `capabilities/builtin/` 下也有独立的完整实现。`core/capability/native.py` 是简化版，被 main.py 直接使用。

### 3.8 Agent Run 调度

固定 Pipeline 已移除。当前运行模型是 Agent Run：
- 每次运行都是独立实例，包含 `run_id/task_id`、`agent_name`、`session_id`、`workspace_id`、目标、状态、进度和输出。
- 调度层负责创建实例、准备工作区、记录 transcript、广播监控事件和处理取消。
- Agent 根据上下文和工具反馈自主决定下一步，不再依赖 YAML 模板步骤。
- `/api/tasks` 是便捷入口，`/api/runs` 是显式多实例运行入口。

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
| `system.yaml` | 直接合并到顶层 | 全局配置 (LLM/Bus/Memory/Server 等；Memory 默认 chroma + ./data/chroma) |
| `agents.yaml` | `agents` (列表) | 15 个 Agent 定义，含 Tools/Skills/MCP/默认工作区 |
| `capabilities.yaml` | `capabilities` (列表) | 22 个能力配置 |
| `mcp_servers.yaml` | `mcp_servers` (列表) | 4 个 stdio MCP 模板，默认 disabled |

### 4.3 加载机制

```python
# config.py 中的三个加载函数:
load_config()           # 合并 config/*.yaml + src/config.yaml + 环境变量
load_yaml_configs()     # 加载 config/ 目录 + 深度合并 + 按文件名分键
load_system_config()    # 类型安全版，返回 Pydantic SystemConfig
```

**环境变量覆盖:**
`LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`,
`MEMORY_BACKEND`, `MEMORY_PERSIST_DIR`, `MEMORY_AUTO_REFLECTION_ENABLED`,
`MEMORY_RECALL_MAX_RESULTS`, `MEMORY_RECALL_SCORE_THRESHOLD`, `BUS_QUEUE_SIZE`, `BUS_HISTORY_SIZE`

记忆默认配置:

```yaml
memory:
  backend: "chroma"
  persist_dir: "./data/chroma"
  collection_name: "agent_memories"
  auto_reflection_enabled: true
  reflection_min_turns: 3
  reflection_max_messages: 12
  recall_max_results: 3
  recall_max_chars: 1200
  recall_score_threshold: 0.0
  fallback_to_memory_on_error: true
  consolidation_threshold: 0.3
  forget_after_days: 1
  forget_min_importance: 0.3
```

若运行环境没有安装 `chromadb`，启动日志会明确提示安装方式；默认允许降级到
内存后端以便开发环境仍能启动，但生产/验收环境应安装依赖并保持 chroma。

工具默认配置:

- `tools.web_search.provider` 在无用户显式配置和无 `WEB_SEARCH_PROVIDER` 环境变量时必须默认为 `duckduckgo`。
- 只有运行时配置、组件配置或环境变量明确写入 `brave` 时，Web Search 才允许使用 Brave Search API。
- `tools.file.workspace_root` 是文件工具、bash 默认 cwd、Agent 运行产物的统一工作区根，默认值为 `./workspace`（相对项目根目录解析）。`AGENTIC_WORKSPACE_ROOT` 或显式配置可覆盖；未显式配置时不得回退到进程 cwd 或 repo root。
- Artifact 默认落在 `./workspace/artifacts`，任务 transcript 默认落在 `./workspace/tasks`，dispatch_agent 临时 worktree 默认落在 `./workspace/worktrees`。这些目录按需自动创建且不入库。

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

### 5.1 REST API (新增 Agent 人格绑定端点)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 获取配置 (隐藏 api_key) |
| POST | `/api/config` | 更新配置 + 热重载 |
| GET | `/api/agents` | 列出所有 Agent |
| GET | `/api/agents/configs` | 列出所有 Agent 的模型/Tools/Skills/MCP/工作区配置视图 |
| GET | `/api/agents/{name}/config` | 获取单个 Agent 的配置视图 |
| GET | `/api/agents/capabilities/list` | 列出 Agent 管理页可选能力 |
| GET | `/api/agents/{name}` | 获取 Agent 详情 |
| GET | `/api/agents/persona-bindings` | 获取 Agent/Session 人格绑定与生效优先级 |
| PUT | `/api/agents/persona-bindings/agents/{agent_name}` | 设置 Agent 默认人格 |
| DELETE | `/api/agents/persona-bindings/agents/{agent_name}` | 解绑 Agent 默认人格，回退到基础人格 |
| PUT | `/api/agents/persona-bindings/sessions/{session_id}` | 设置会话人格绑定 |
| DELETE | `/api/agents/persona-bindings/sessions/{session_id}` | 解绑会话人格 |
| POST | `/api/agents/{name}/invoke` | 直接调用 Agent |
| GET | `/api/personas` | 列出人格定义 |
| POST | `/api/personas` | 创建人格定义 (受管理员 token 边界保护) |
| GET | `/api/personas/{persona_id}` | 获取人格详情 |
| PUT | `/api/personas/{persona_id}` | 编辑人格定义并生成新版本 |
| DELETE | `/api/personas/{persona_id}` | 安全归档人格；不会物理删除，且会清理指向该人格的绑定 |
| POST | `/api/personas/{persona_id}/restore` | 恢复已归档人格 |
| GET | `/api/personas/{persona_id}/versions` | 获取人格版本历史 |
| POST | `/api/personas/{persona_id}/rollback` | 管理员确认后回滚人格版本 |
| GET | `/api/personas/proposals` | 列出人格迭代建议 |
| POST | `/api/personas/{persona_id}/proposals` | 生成 pending 人格迭代建议 |
| POST | `/api/personas/proposals/{proposal_id}/approve` | 管理员批准 pending 建议并生成新版本 |
| POST | `/api/personas/proposals/{proposal_id}/reject` | 拒绝 pending 建议 |
| POST | `/api/tasks` | 提交新任务 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{task_id}` | 获取任务详情 |
| DELETE | `/api/tasks/{task_id}` | 取消任务 |
| POST | `/api/runs` | 创建 Agent Run |
| GET | `/api/runs` | 列出 Agent Run |
| GET | `/api/runs/{run_id}` | 获取运行详情 |
| GET | `/api/runs/{run_id}/events` | 读取运行事件流 |
| POST | `/api/runs/{run_id}/control` | 控制运行 |
| DELETE | `/api/runs/{run_id}` | 取消运行 |
| GET | `/api/runs/workspaces` | 汇总运行工作区 |
| GET | `/api/memory/stats` | 记忆统计 |
| GET | `/api/memory/list` | 列出记忆 |
| POST | `/api/memory/search` | 搜索记忆 |
| POST | `/api/memory/create` | 创建记忆 |
| PUT | `/api/memory/{memory_id}` | 更新记忆 |
| DELETE | `/api/memory/{memory_id}` | 删除记忆 |
| GET | `/api/memory/settings` | 获取记忆设置与运行状态 |
| POST | `/api/memory/settings` | 保存记忆设置 |
| POST | `/api/memory/consolidate` | 记忆巩固 |
| POST | `/api/memory/forget` | 记忆遗忘 |

### 5.2 WebSocket

`ws://localhost:8001/ws` — 实时通信。聊天回复仅回当前连接，系统监控事件单独广播。

---

## 6. 前端架构

**技术栈:** React 18 + TypeScript 5 + Vite 5 (无第三方 UI 库)

**状态管理:** `useReducer` + React Context (`AppProvider`)

**当前工作台页面/组件:**

| 组件 | 功能 |
|------|------|
| `Sidebar` | 侧边栏导航 |
| `Topbar` | 页面标题、工作区选择器、实时通道状态 |
| `OverviewPanel` | 后端健康、运行状态、最近事件总览 |
| `ChatPanel` | 会话化聊天、附件、工作区绑定、工具/产物展示 |
| `ChatroomPanel` | 多 Agent 聊天室、host、目标、Todo、@ 成员协作 |
| `WorkspacePanel` | zip 导入、工作区管理、文件树、文本读写 |
| `AgentPanel` | Agent 配置、模型、Tools、Skills、MCP、默认工作区 |
| `RunsPanel` | Agent Run 创建、筛选、详情、Process View、raw events、取消 |
| `MemoryPanel` | 记忆统计/列表/搜索/创建/删除/设置/遗忘周期 |
| `MonitorPanel` | 系统监控 (连接状态、按 Agent 聚合的运行进展、事件流) |
| `ToolsPanel` | Tool 能力库装配/卸下 |
| `SkillsPanel` | Skill 能力库与 Agent Skills 配置 |
| `McpPanel` | MCP 模板库与 Agent MCP 配置 |
| `PersonaPanel` | 人格定义、版本、绑定、建议审核 |
| `LoginPage` | 可选全局访问密码门禁 |
| `Settings` | LLM/工具配置面板 (热重载) |

---

## 7. 实现路线图

### Phase 1: 核心基础设施 ✅
- [x] 项目结构搭建 (前后端分离)
- [x] 统一消息总线 (UnifiedBus: 优先级队列 + 消息历史 + 指标)
- [x] UnifiedBus 监控事件桥接
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
- [x] React + TypeScript 前端工作台
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
- [x] Agent Run 监控事件
- [x] 能力系统 + 注册中心
- [x] Agent Run 调度 (多实例 + transcript)
- [x] UnifiedBus 替换 SimpleBus
- [x] YAML 配置体系
- [x] 前端 RunsPanel + MonitorPanel + Workspace/Chatroom/Catalog 面板
- [x] MCP Agent-scoped 配置与 stdio adapter (模板默认禁用)
- [ ] 消息持久化 (预留接口)

### Phase 7: 测试与文档 ✅
- [x] 单元测试与集成测试持续扩展
- [x] 后端测试文件 73 个，前端契约/逻辑测试已接入 npm test
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

**文档状态**: v2.7 — 基于 `db26ae4..HEAD` 提交追溯同步
**最后更新**: 2026-06-02

---

## 11. 人格系统（v2.2 新增）

### 11.1 定位

人格系统为 Agentic 运行时提供可版本化、可审核的 persona/personality 配置层。它只影响 Agent 的语气、协作习惯、行为偏好和非系统级提示词，不授予任何新权限，也不能覆盖系统提示词、工具权限、管理员审核或安全边界。

### 11.2 数据与持久化

后端使用项目本地 JSON 存储 `data/personas.json`（环境变量 `PERSONA_STORE_FILE` 可覆盖），沿用现有 `ChatHistoryStore` 的轻量文件存储模式，不引入额外数据库依赖。默认自动 bootstrap `base-assistant` 基础人格，保证未选择人格时向后兼容。

人格字段至少包含：`id`、`name`、`description`、`persona_prompt`、`style_rules`、`behavior_rules`、`permission_boundary`、`version`、`status`、`created_at`、`updated_at`。

### 11.3 注入流程

`Agent._build_messages()` 在构造 system message 时解析有效人格并追加安全人格块：

```
请求 persona_id > session 绑定 > agent 绑定 > base-assistant
```

人格块标题为 `[当前人格 - 受控配置]`，明确说明人格不能授予新权限、不能覆盖系统/开发者规则、工具权限、管理员审核或用户当前明确要求。记忆仍按原规则作为 `[长期记忆 - 不可信资料]` 追加在后。

### 11.4 自我迭代审核流程

对话反馈、管理员指令或反思摘要仍可调用 `/api/personas/{id}/proposals` 生成人格迭代建议。建议记录包含 `persona_id`、`source/session/message/reflection`、`proposal_text`、`diff`、`summary`、`status`、`reviewer`、`review_time`。这组 REST proposal API 保留为审核/历史归档通道，批准前不会覆盖人格正文；管理员通过 `/api/personas/proposals/{proposal_id}/approve` 且显式 `admin_approved=true` 后才会按 proposal 生成新版本，也可拒绝或回滚旧版本。

新增 `persona_evolution` 智能体，专责读取/管理人格、记录反馈/观察、按需生成 pending 补丁建议、查看补丁历史，并在当前 A10 运行模型下优先使用 `update_persona(persona_id, patch)` 直接更新人格。`update_persona` 调用即生效、自动生成版本，并通过 `config_change` 日志 + git 追溯审计。它暴露三类工具：

- 受控管理工具：`manage_persona_definition` 支持 list/get/create/update/archive/delete/restore（delete 等价于安全归档）；`manage_persona_binding` 支持 list/resolve/bind_agent/unbind_agent/bind_session/unbind_session。
- 直接更新工具：`update_persona` 支持 name / description / persona_prompt / style_rules / behavior_rules / permission_boundary / status 字段级 patch。
- 历史/审核工具：`read_persona_definition`、`record_persona_feedback`、`generate_persona_patch_proposal`、`apply_confirmed_persona_patch`、`list_persona_patch_history`。旧 proposal 数据保留可查，新流程不再强制走 propose+approve。

`manage_persona_definition` / `manage_persona_binding` 的写入类 operation 仍要求 `admin_approved=true` 和 `reviewer`，若配置 `PERSONA_ADMIN_TOKEN` 还必须提供匹配 token；`update_persona` 是 A10 之后的直接更新路径，不再要求这些审批字段。普通 Agent 不直接挂载这些写入工具；Assistant 遇到人格创建、编辑、归档或绑定需求时应委派 `persona_evolution`，不要误用 `agent_creator` 创建 Agent。

### 11.5 绑定职责与前端入口

“人格”面板只负责人格定义管理、预览/测试、迭代建议生成与审核、版本历史与回滚。Agent 角色到人格的绑定属于“智能体/Agent”页面，调用 `/api/agents/persona-bindings*` 端点，并在 UI 中明确展示生效顺序：请求指定人格 > 会话绑定 > Agent 绑定 > 基础人格。绑定页面缓存人格与绑定数据，普通进入页面不重复强制加载；手动刷新或写操作后才失效重取。旧 `/api/personas/bindings*` 端点保留为兼容别名，不再作为新 UI 的首选入口。

---

## 12. AstrBot 前端 Artifact / 附件能力（v2.3 新增）

### 12.1 定位

系统新增与 AstrBot 前端关联的 Artifact 能力，用于把 Agent 或用户生成的 HTML、Markdown、代码、图片和普通文件保存为前端可见对象，并提供类似 Claude 网页版 Artifact 的预览、切换、下载和新窗口打开体验。该能力是最小闭环实现，不改变原有聊天、任务、记忆和 Agent API。

### 12.2 后端数据流

- 存储层：`backend/src/core/artifacts.py` 默认使用项目根目录下 `workspace/artifacts/` 保存 `artifacts.json` manifest 和文件内容；环境变量 `ARTIFACT_STORE_DIR` 可覆盖。
- REST API：`backend/src/api/routes/artifacts.py`
  - `GET /api/artifacts?session_id=&limit=` 列出 Artifact。
  - `POST /api/artifacts` 创建文本或 base64 文件 Artifact。
  - `GET /api/artifacts/{id}` 获取元数据。
  - `GET /api/artifacts/{id}/content` 获取可文本预览内容。
  - `GET /api/artifacts/{id}/download` 下载文件。
  - `GET /api/artifacts/{id}/open` inline 打开/预览文件。
  - `DELETE /api/artifacts/{id}` 删除 Artifact。
- Agent 能力：`create_frontend_artifact` 位于 `backend/src/capabilities/tools/frontend_artifact.py`，已挂载到 assistant。Agent 需要把长 HTML/Markdown/代码/图片/文件交给前端展示时，应调用该工具而不是只把内容粘贴到聊天正文。
- 会话兼容：`ChatMessageCreateRequest` 和 `ChatHistoryStore` 支持保存消息级 `artifacts` 字段；旧消息不受影响。

### 12.3 前端体验

`ChatPanel` 会从消息 `artifacts`、工具结果中的 `artifact/artifacts` 自动收集对象，在消息气泡中显示 Artifact chip。点击 chip 后打开右侧预览栏：

- HTML：使用 sandbox iframe 预览。
- Markdown/代码/文本：以只读文本预览。
- 图片：直接使用 `/open` inline 预览。
- 其它文件：显示下载/打开入口。

预览栏提供“下载”和“打开”操作；关闭后保留右下角 Artifact rail，可重新打开当前会话的 Artifact 列表入口。

### 12.4 安全边界

- Artifact 内容视为不可信资料。HTML 预览使用 iframe sandbox，避免覆盖主应用上下文。
- 后端只从本地 Artifact store 读取文件，文件名会清洗；不暴露任意路径读取。
- 不应把密钥、token、个人隐私或临时日志写入 Artifact。
- 当前实现不做权限隔离，适合本地 AstrBot/毕业设计演示；生产环境需增加用户/会话鉴权、配额和清理策略。


---

## 13. 进化中心的系统架构仪表盘（v2.4 新增）

“进化”页面定位为 **Agentic System Architecture Dashboard + Evolution Command Center**，不再把 assistant、Agent CRUD 或 Tool CRUD 误表达为进化本身。assistant 只是系统组件之一；真实进化应先观察当前架构状态，再生成可执行的系统级改造任务。

### 13.1 后端聚合接口

- `GET /api/evolution/system-status` 聚合运行时状态：AgentRegistry、CapabilityRegistry、MemoryStore/Formation/Buffer、LLM 配置、Agent Run、UnifiedBus 指标、config 文件和 Task 统计。
- `POST /api/evolution/command` 接收 `goal`，基于当前状态生成一条明确进化指令，可提交给现有 Agent Run 执行。
- 原有 `/api/evolution/graph`、动态 Tool、Tool prompt 和 reload API 保持兼容；它们是组件维护接口，不等同于进化页主叙事。

### 13.2 前端表达

进化页按系统组成展示：Assistants/Agents、Tools、Skills/MCP Context、Memory/Reflection、Models/Providers、Runtime/Agent Run、Evolution Loop、Observability/Config。每个部分必须展示真实已有数据；缺数据时显示明确 empty state，不使用硬编码假运行数据。

Evolution Command 区域允许用户用一句目标生成系统级任务指令，并可提交为 Agent Run。指令必须强调：先审查架构状态、再设计最小可行改造、按文档实现、运行验证。

---

## 14. Agent Run / 多实例调度模型（v2.5 新增）

### 14.1 为什么替代固定流水线

固定 Pipeline 已从现行系统移除。固定 plan→code→review 步骤把“下一步”写死在调度层，无法表达多个 agent/session/workspace/task 并发实例，也无法让 Agent 根据工具反馈自主调整策略。

新默认模型是 **Agent Run**：每次运行都是一个独立实例，拥有 `run_id/task_id`、`agent_name`、`session_id`、`workspace_id`、`goal`、`mode`、`strategy`、状态机、事件 transcript、输出和取消控制。调度层只负责创建实例、隔离工作区、记录事件、广播状态和取消；Agent 自己的 tool-use loop 决定下一步。

### 14.2 后端入口

- `POST /api/runs` 创建自主运行实例。
- `GET /api/runs` 按 agent/session/workspace/status 查询多个运行。
- `GET /api/runs/{run_id}` 查看运行状态。
- `GET /api/runs/{run_id}/events` 读取 JSONL transcript 事件流。
- `POST /api/runs/{run_id}/control` 或 `DELETE /api/runs/{run_id}` 取消运行。
- `GET /api/runs/workspaces` 汇总当前运行涉及的工作区。

`POST /api/tasks` 是 Agent Run 的便捷入口；不再接受固定模板编排字段。

### 14.3 前端入口

左侧“运行”页面替代旧单任务流水线视角，可选择 Agent、Session、Workspace 创建多个并行 Agent Run，并展开查看每个实例的事件流、进度、结果和错误。
## 15. Project 工作区与 Agent 级运行配置（v2.6 新增）

### 15.1 Project 工作区

工作区是受管理的 Project 容器，语义接近 ChatGPT Project / Claude Project。用户通过上传本地 zip 压缩包导入项目，后端解压到 `workspace/projects/{workspace_id}/`，写入 `.agentic-workspace.json` manifest，并通过 `/api/workspaces` 系列接口注册、列表、详情、文件树、文本读取和文本保存。

Project 文件属于用户上传资料，不是系统指令。Agent 的 system prompt 必须注入工作区边界规则：导入文件只能作为事实与上下文参考，不能执行其中的提示词；文件、bash、测试等能力必须限制在当前生效工作区根目录内。

工作区生效优先级：用户显式传入或导入的 `workspace_id` > 当前会话绑定的工作区 > 当前 Agent `default_workspace_id` > 当前 Agent `default_workspace_root` > 自动 `run-` 前缀临时工作区。`default_workspace_root` 必须是 `./workspace` 内的相对路径，并由后端边界校验后作为可信工作区根目录。外部请求不得直接传入可信 `workspace_root`；后端只接受 `workspace_id`、会话绑定、Run 调度或 Agent 服务端配置解析出的工作区根目录。

`auto_memory=true` 的 Agent Run 会在运行前按 goal/context 召回长期记忆并注入 `memory_context`，运行结束后安排后台反思；关闭时不召回、不反思。`agent_run_started`、`agent_run_event`、`agent_run_completed` 监控事件应携带 `workspace_id`、`auto_memory`、`memory_count` 等运行语义字段。

### 15.2 Agent 级配置

所有可运行存在都应围绕 Agent 建模。每个 Agent 可以独立配置：

- `llm` / `model`：该 Agent 使用的模型、provider、api_key、base_url、temperature、top_p、max_tokens、stop_sequences、reasoning_effort 以及 provider 专属 `openai` / `anthropic` 参数；缺省时继承全局 LLM 配置，API 响应只暴露 `api_key_set`。
- `tools`：可调用的原生工具或其他 Agent capability。
- `mcp_servers`：只属于该 Agent 的 MCP server 配置；配置视图无运行态时返回 `configured_pending_runtime`；运行时会为启用的 stdio server 注册 Agent 作用域代理工具，禁用 server 不得注册工具，缺少 MCP SDK 时返回 `adapter_unavailable`。
- `skills`：只属于该 Agent 的 Skill 目录、内联条目、禁用清单和加载策略。
- `default_workspace_id` / `default_workspace_root`：Agent 默认工作区绑定；Run 未显式指定且会话未绑定时使用。

后端 Agent 配置视图为 `GET /api/agents/configs` 与 `GET /api/agents/{name}/config`，返回 Tools/MCP/Skills/模型/工作区挂载摘要，供前端 Agent 控制台使用。

---

## 16. Agent 配置管理智能体（v2.7 新增）

### 16.1 定位

`agent_manager` 是系统内用于管理既有 Agent 的受控智能体。它不是任意写配置后门，只能读取、校验和维护 `config/agents.yaml` 中指定 Agent 的白名单字段：`description`、`system_prompt`、`tools`、`output_format`、`max_iterations`、`llm`、`skills`、`mcp_servers`、`default_workspace_id`、`default_workspace_root`。当前 A10 运行模型中，写入由 `update_agent_config` 直接完成并热重载，不再要求 `admin_approved` / `reviewer` / `admin_token`；审计依赖 `config_change` 日志和 git diff/commit。

新增 Agent 仍由 `agent_creator` 负责；Persona/personality 仍由 `persona_evolution` 负责。Assistant 遇到现有 Agent 的提示词优化、模型切换、Tools/Skills/MCP 挂载或默认工作区配置调整时，应委派 `agent_manager`。

### 16.2 受控工具链

`agent_manager` 只挂载三个工具：

- `read_agent_config`：只读列出或读取 Agent 配置，返回时隐藏 `llm.api_key`，只暴露 `api_key_set`。
- `validate_agent_config_patch`：只读校验字段白名单、高风险工具、模型参数、MCP 配置和工作区字段。
- `update_agent_config`：合并字段级 patch 到目标 Agent，调用即生效并触发热重载；热重载失败会回滚 `agents.yaml`。

高风险工具治理已下沉到配置校验与 `system.yaml` 风险策略：`update_agent_config` 会做字段白名单、MCP、模型、工作区和管理工具挂载校验。MCP server 由所属 Agent 独占；运行时只为启用的 stdio server 注册 Agent 作用域代理工具，禁用 server 不得注册工具，状态只能在 `configured_pending_runtime`、`proxy_available`、`partial`、`adapter_unavailable` 等可解释状态中更新。

### 16.3 安全与生效

Agent 独立模型配置支持 `llm.provider/model/base_url/temperature/top_p/max_tokens/stop_sequences/reasoning_effort/openai/anthropic/api_key`。读取和返回结果永不明文返回 `api_key`；写入时 `********`、`••••••••` 等掩码值不会覆盖已有密钥。

`agent_manager` 本身属于关键系统 Agent，管理页不应删除它。普通 Agent 不直接挂载 Agent 配置写入工具；只有 `assistant` 可委派 `agent_manager`，而 `agent_manager` 再按白名单边界调用受控工具。
