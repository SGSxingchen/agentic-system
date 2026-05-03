# 基于多智能体协作的自动化代码生成与审查系统

> 本科毕业设计项目 | 2026 届

## 项目简介

本系统采用**事件驱动的多智能体协作架构**，实现从需求分析到代码生成再到自动审查的全流程自动化。系统包含四个核心智能体（助手、规划、编码、审查），通过统一消息总线进行事件驱动通信，支持 YAML 配置驱动的工作流编排，并配备长期记忆系统（情景/语义/程序三种记忆类型），实现智能体间的高效协作。

前后端分离设计：后端基于 FastAPI + Python asyncio，前端基于 React + TypeScript + Vite，通过 REST API 和 WebSocket 实时通信。

## 核心特色：可进化私人助理

本项目的差异化定位不是单个固定聊天机器人，而是一个**可进化的私人助理运行时**：

- **主 Agent 调度子 Agent**：`assistant` 是主控 Agent，`planner`、`coder`、`reviewer` 等子 Agent 会被包装成标准 Tool，主 Agent 可按需委派任务。
- **Agent 即能力**：系统通过 `AgentCapability` 将任意 Agent 注册到统一能力注册表，因此工作流和其他 Agent 不需要区分“工具”还是“智能体”。
- **运行时装载新 Tool**：新增 `DynamicToolCapability`，支持 `template`、`checklist`、`regex_extract` 三种安全动态工具，可通过 API/前端创建，无需写 Python 插件。
- **能力热挂载**：动态 Tool 创建后可立即挂载到 `assistant` 或其他 Agent，并触发 Agent 热重载。
- **Tool 提示词可视化配置**：网页可直接修改暴露给 LLM 的 Tool 提示词，JSON Schema 只读，避免误改工具入参协议。
- **进化中心可视化**：前端新增“进化中心”，展示 Agent-Tool 能力网络、主 Agent 委派关系、动态 Tool 库和子 Agent 创建入口。

---

## 技术栈

| 分类 | 技术 | 版本 |
|------|------|------|
| **后端框架** | FastAPI | ≥ 0.100 |
| **ASGI 服务器** | Uvicorn | ≥ 0.20 |
| **数据验证** | Pydantic | ≥ 2.0 |
| **LLM - OpenAI** | openai SDK | ≥ 1.0 |
| **LLM - Anthropic** | anthropic SDK | ≥ 0.20 |
| **配置管理** | PyYAML | ≥ 6.0 |
| **日志** | structlog | ≥ 23.0 |
| **向量数据库** | ChromaDB | 可选 |
| **前端框架** | React | 18.x |
| **前端语言** | TypeScript | 5.3+ |
| **构建工具** | Vite | 5.x |
| **运行时** | Python 3.10+ / Node.js 18+ | |

---

## 项目结构

```
agentic-system/
├── config/                         # YAML 配置 (agents/triggers/workflows/capabilities/system)
├── backend/
│   ├── src/
│   │   ├── agents/                 # 4 个智能体 (assistant/planner/coder/reviewer)
│   │   ├── api/                    # FastAPI 应用 (routes/websocket/schemas/dependencies)
│   │   ├── core/                   # 核心框架
│   │   │   ├── bus/                #   统一消息总线 (UnifiedBus)
│   │   │   ├── event/              #   事件引擎 + 扳机系统
│   │   │   ├── memory/             #   长期记忆系统
│   │   │   ├── capability/         #   能力插件系统
│   │   │   ├── workflow/           #   工作流编排器
│   │   │   ├── context/            #   上下文管理
│   │   │   ├── llm/                #   LLM 客户端 (OpenAI/Anthropic)
│   │   │   └── config.py           #   配置管理
│   │   ├── capabilities/builtin/   # 完整能力实现 (代码解析/静态分析/测试运行)
│   │   └── utils/                  # 日志 + 追踪
│   ├── tests/                      # 测试 (unit + integration)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/             # 9 个面板 (Chat/Agent/Task/Workflow/Memory/Monitor/Evolution/Settings/Sidebar)
│       ├── hooks/                  # WebSocket Hook
│       ├── store/                  # 全局状态管理
│       └── api/                    # API 客户端
├── docs/                           # 项目文档 (architecture/api/deployment/bus-design)
├── CLAUDE.md                       # 架构设计文档 (详细)
├── QUICKSTART.md                   # 快速开始指南
├── HANDOFF.md                      # 交接文档
└── README.md                       # ← 本文件
```

---

## 已实现功能

### 🤖 智能体系统
- **AssistantAgent** — 对话助手，集成记忆检索，支持上下文感知对话
- **PlannerAgent** — 任务规划，将需求分解为可执行的子任务列表 (结构化 JSON)
- **CoderAgent** — 代码生成，结构化输出（文件名 + 代码 + 说明）
- **ReviewerAgent** — 代码审查，六维度评估（正确性/安全性/可维护性/性能/最佳实践/错误处理）
- **Agent-as-Tool** — 任意 Agent 可被包装成 Capability，供主 Agent 或其他 Agent 调用

### 📡 消息总线 & 事件引擎
- **UnifiedBus** — 统一消息总线，支持发布/订阅、请求/响应、广播、点对点
- 优先级队列、消息历史、运行指标统计
- 事件引擎 + 扳机系统 (Trigger)，支持条件匹配、优先级、异步/同步调度

### 🧠 长期记忆系统
- 三种记忆类型：情景记忆 / 语义记忆 / 程序性记忆
- 双后端存储：InMemory + ChromaDB（向量数据库，可选）
- 多信号加权检索（相关性 + 重要性 + 时间衰减 + 访问频率）
- 记忆巩固（去重合并）+ 记忆遗忘（时间衰减）
- 完整 REST API：CRUD + 搜索 + 巩固 + 遗忘

### 🔧 能力系统
- 能力抽象接口 + JSON Schema 描述
- 内置能力：代码解析器 (AST)、静态分析器、测试运行器
- 常规助理工具：`calculator`、`datetime_tool`、`web_fetch`、`file_search`、`json_tool`、`text_processor`
- 工作区工具：`read_file`、`write_file`、`bash`（默认关闭，需显式启用）。默认工作区为项目根目录下 `./workspace`，bash 默认在该目录执行，工具生成的临时/中间产物默认落在该目录。
- 能力注册中心，支持动态加载
- 动态能力：通过配置/API 创建 `template`、`checklist`、`regex_extract` Tool，并热挂载到 Agent
- Tool 提示词管理：可编辑 LLM-facing prompt，JSON Schema 只读

### 🔄 工作流编排
- 顺序执行、并行执行、YAML 配置驱动
- 预定义工作流模板（规划→编码→审查→修复）
- 分层上下文存储（全局/会话/智能体三层）

### 🌐 WebSocket 实时通信
- 对话响应只回发到当前连接，避免不同浏览器会话互相串消息
- Pipeline 监控事件单独广播到监控面板，不混入聊天回复
- 所有推送消息统一附带时间戳，便于前端事件流展示

### 🖥️ 前端界面 (9 个面板)
- **ChatPanel** — 聊天气泡界面，显示记忆使用指示
- **AgentPanel** — 智能体状态查看与直接调用
- **TaskPanel** — 任务提交与状态跟踪
- **WorkflowPanel** — 工作流模板选择与执行
- **MemoryPanel** — 记忆统计/列表/搜索/创建/删除
- **MonitorPanel** — 系统状态可视化
- **Settings** — LLM 配置面板（支持热重载）
- **Sidebar** — 侧边栏导航
- **EvolutionPanel** — 进化中心：能力网络可视化、动态 Tool 创建、子 Agent 创建

### 🛠️ 基础设施
- YAML 配置体系 (5 个配置文件 + 动态加载 + fallback)
- 统一日志系统 (structlog)
- 调用追踪器 (Tracer/Span)
- Pydantic 类型安全配置

---

## 安装与运行

### 环境要求

- Python 3.10+
- Node.js 18+
- npm

### 1. 克隆项目

```bash
git clone <repo-url>
cd agentic-system
```

### 2. 后端安装与启动

```bash
# 创建虚拟环境 (推荐)
cd backend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置 LLM (任选其一)
# 方式 1: 编辑配置文件
cp config.example.yaml src/config.yaml
# 编辑 src/config.yaml，填入 LLM API Key

# 方式 2: 环境变量
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-your-key
export LLM_MODEL=gpt-4

# 启动后端 (二选一)
cd src && python -m api.main
# 或
cd src && uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

后端将在 **http://localhost:8001** 启动。

### 3. 前端安装与启动

```bash
cd frontend
npm install
npm run dev
```

前端将在 **http://localhost:3000** 启动。

### 4. 访问系统

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | 前端界面 |
| http://localhost:8001/docs | Swagger API 文档 |
| http://localhost:8001/api/health | 健康检查 |
| ws://localhost:8001/ws | WebSocket 实时通信 |

---

## 测试与验证

```bash
# 后端单元 + 集成测试
python3 -m pytest backend/tests/ -q

# 真实 LLM 冒烟验证（建议日常回归优先使用）
python3 tests/api_live_test.py --suite smoke

# 真实 LLM 全量 API 验证
python3 tests/api_live_test.py
```

`--suite smoke` 会优先验证最关键的真实链路：
- `/api/agents/assistant/invoke`
- `task_decompose_and_execute`
- `code_generation_and_review`
- WebSocket 连通性

如果在 Windows 终端运行 live 脚本时遇到编码问题，可先设置：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

---

## 配置说明

### 运行时配置 (backend/src/config.yaml)

`backend/src/config.yaml` 现在只作为本地运行时覆盖项，适合放未提交的个人配置；实际加载优先级为：

1. `config/*.yaml`
2. `backend/src/config.yaml`
3. 环境变量

敏感信息请优先使用环境变量注入，避免把真实密钥提交到仓库。

```yaml
llm:
  provider: openai          # openai 或 anthropic
  model: gpt-4              # 模型名称
  api_key: sk-xxx           # API Key (建议用环境变量 LLM_API_KEY)
  base_url: ""              # 自定义 API 端点 (可选)

memory:
  backend: "chroma"         # 默认 ChromaDB 持久化；开发测试可改 "memory"
  persist_dir: "./data/chroma"
  reflection_min_turns: 3   # 默认累计 3 轮后反思；显著偏好/待办/项目决策可提前触发
  reflection_max_messages: 12
```

对话记忆现在不是只靠 `/api/memory/create` 手动写入：REST chat、SSE stream 和
WebSocket 流式聊天会在完整回复结束后后台追加到反思缓冲，默认累计后生成结构化
记忆；如果用户明确说“记住/以后默认/我喜欢/待办/需求变更”等显著长期信息，会
提前触发。下一次生成前会
检索相关记忆，并以「不可信资料」方式注入上下文。可用以下脚本验证持久化闭环:

```bash
python scripts/verify_memory_persistence.py
```

### 组件配置 (config/ 目录)

| 文件 | 用途 |
|------|------|
| `config/agents.yaml` | 智能体定义 (名称/类型/能力) |
| `config/triggers.yaml` | 事件扳机规则 |
| `config/workflows.yaml` | 工作流模板 |
| `config/capabilities.yaml` | 能力插件 |
| `config/system.yaml` | 全局系统配置 |

补充说明:
- 默认服务监听地址已收紧为 `127.0.0.1`
- `bash` 工具默认关闭，只有在显式设置 `ENABLE_SHELL_TOOL=true` 时才允许使用；启用后默认 cwd 是项目根目录下 `./workspace`，可用 `tools.file.workspace_root` / `AGENTIC_WORKSPACE_ROOT` 改为显式目录。

### 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | LLM 提供商 (openai/anthropic) |
| `LLM_API_KEY` | LLM API Key |
| `LLM_MODEL` | 模型名称 |
| `LLM_BASE_URL` | 自定义 API 端点 |
| `MEMORY_BACKEND` | 记忆后端 (memory/chroma) |

---

## 运行测试

```bash
# 全部测试
python3 -m pytest backend/tests/ -q

# 单元测试
python3 -m pytest backend/tests/unit/ -v

# 集成测试
python3 -m pytest backend/tests/integration/ -v

# 查看详细输出
python3 -m pytest backend/tests/ -v --tb=short
```

### 测试模块

| 模块 | 文件 | 覆盖范围 |
|------|------|----------|
| 消息总线 | `test_bus.py` | SimpleBus / UnifiedBus / 频道 / 路由 |
| 智能体 | `test_agent_system.py` | 基类 / 生命周期 / 注册中心 |
| 事件引擎 | `test_event_engine.py` | 事件匹配 / 扳机 / 条件评估 |
| 能力系统 | `test_capability.py` | 代码解析 / 静态分析 / 注册 |
| 常规工具 | `test_common_tools.py` | 计算 / 时间 / 网页读取 / 文件搜索 / JSON / 文本处理 |
| 配置管理 | `test_config.py` | 配置加载 / 环境变量 / YAML 合并 |
| 上下文 | `test_context.py` | 分层存储 |
| 记忆系统 | `test_memory.py` | 存储 / 检索 / 巩固 / 遗忘 |
| 规划器 | `test_planner.py` | PlannerAgent 逻辑 |
| 工作流 | `test_workflow.py` | 顺序 / 并行执行 |
| 工作流边界 | `test_workflow_edge_cases.py` | 工作流边界条件 |
| 集成-流水线 | `test_agent_pipeline.py` | 多智能体协作流程 |
| 集成-API | `test_api.py` | REST API 端点 |

---

## API 端点

### 智能体管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents` | 列出所有已注册智能体 |
| GET | `/api/agents/{name}` | 获取特定智能体详情 |
| POST | `/api/agents/{name}/invoke` | 直接调用某个智能体 |

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks` | 提交新任务 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{task_id}` | 获取任务详情 |
| DELETE | `/api/tasks/{task_id}` | 取消/删除任务 |

### 工作流

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workflows/templates` | 获取预定义工作流模板 |
| POST | `/api/workflows/execute` | 执行工作流 |

### 记忆系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory/stats` | 记忆统计 |
| GET | `/api/memory/list` | 列出记忆 (支持类型过滤) |
| POST | `/api/memory/search` | 搜索记忆 |
| POST | `/api/memory/create` | 创建记忆 |
| DELETE | `/api/memory/{memory_id}` | 删除记忆 |
| POST | `/api/memory/consolidate` | 触发记忆巩固 |
| POST | `/api/memory/forget` | 触发记忆遗忘 |

### 配置与健康

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前配置 (隐藏 API Key) |
| POST | `/api/config` | 更新配置并热重载 |
| GET | `/api/health` | 健康检查 |

### WebSocket

| 路径 | 说明 |
|------|------|
| `ws://localhost:8001/ws` | 实时通信端点 |

---

## 前端面板功能描述

| 面板 | 功能说明 |
|------|----------|
| **聊天面板** | 用户与 AI 的对话界面，显示聊天气泡，支持记忆使用指示 |
| **智能体面板** | 列出所有已注册的智能体，查看状态和能力列表，可直接调用 |
| **任务面板** | 提交开发需求，触发 规划→编码→审查 流水线，跟踪任务状态 |
| **工作流面板** | 选择预设工作流模板 (如完整流水线)，配置参数后执行 |
| **记忆面板** | 查看记忆统计 (三种类型分布)，列表浏览，搜索，手动创建/删除 |
| **监控面板** | 系统实时状态，WebSocket 连接状态，事件流日志 |
| **设置面板** | LLM 提供商切换，API Key 配置，模型选择，自定义 base_url |

---

## 项目统计

| 指标 | 数值 |
|------|------|
| 源代码文件 | ~109 个 (82 Python + 16 TS/TSX + 11 CSS) |
| 后端代码行数 | ~8,300 行 |
| 前端代码行数 | ~5,100 行 |
| 测试代码行数 | ~4,900 行 |
| 测试用例 | 550 个 |
| 测试模块 | 16 个 |
| REST API 端点 | 31 个 |
| 前端面板 | 9 个 |
| YAML 配置文件 | 6 个 |

---

## 文档索引

| 文档 | 说明 |
|------|------|
| `CLAUDE.md` | 架构设计文档 (详细，面向 AI 和开发者) |
| `README.md` | 项目说明 (面向用户和评审) |
| `QUICKSTART.md` | 5 分钟快速上手 |
| `HANDOFF.md` | 交接文档 (状态概览 + 下一步) |
| `PROGRESS.md` | 开发进度追踪 |
| `docs/architecture.md` | 系统架构 |
| `docs/api.md` | API 端点详细文档 |
| `docs/bus-design.md` | 消息总线设计 |
| `docs/deployment.md` | 部署指南 |

---

## 开发规范

- 所有改动遵循「先文档 → 再编码 → 再验收」流程
- Python: PEP 8 + 类型注解 + Google 风格 docstring
- TypeScript: 严格模式 + 函数式组件
- 提交: [Conventional Commits](https://www.conventionalcommits.org/) 规范
- 架构变动须同步更新 `CLAUDE.md` 和相关文档
