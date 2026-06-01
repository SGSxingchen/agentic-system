# 基于多智能体协作的自动化代码生成与审查系统

> 本科毕业设计项目 | 2026 届
> 文档同步时间: 2026-06-02
> 本 README 已按 `db26ae4..HEAD` 提交追溯同步，覆盖 Agent Run、项目工作区、聊天室协作团队、能力库、MCP、附件、Artifact、认证与最新前端工作台。

## 项目简介

本系统是一个事件驱动的多智能体协作平台，面向“需求分析、代码生成、自动审查、运行观测、能力扩展”的完整流程。后端使用 FastAPI + asyncio，前端使用 React + TypeScript + Vite。系统通过统一消息总线、配置化 Agent、工具能力注册表、长期记忆、项目工作区和 transcript 事件流，把一次用户需求组织成可观察、可回放、可审查的 Agent Run。

当前系统已经从早期固定 Pipeline 迁移为 **Agent Run 多实例调度模型**：每次运行都有独立 `run_id/task_id`、`agent_name`、`session_id`、`workspace_id`、目标、状态、进度、输出和事件流。调度层不再写死 plan -> code -> review 步骤，而是让 Agent 根据上下文与工具反馈自主推进。

## 当前核心能力

### 1. Agent Run 多实例调度

- `POST /api/runs` 创建自主运行实例，`POST /api/tasks` 作为兼容便捷入口。
- 每个 Run 可绑定 Agent、Session、Project 工作区和长期记忆召回开关。
- transcript 以 JSONL 记录 `created`、`started`、`thinking`、`tool_call`、`tool_result`、`done`、`error` 等事件。
- 前端“运行”页面可查看 run 状态、进度、工具调用、最终输出和事件流。
- 支持取消控制，终态为 `completed`、`failed` 或 `killed`。

### 2. 15 个配置化 Agent

Agent 不再依赖 `backend/src/agents/` 里的硬编码类，而是由 `config/agents.yaml` 配置生成，并通过统一能力注册表暴露为可调用能力。

| 分组 | Agent |
|------|-------|
| 核心协作 | `assistant`、`planner`、`coder`、`reviewer` |
| 系统进化与管理 | `tool_creator`、`agent_creator`、`agent_manager`、`persona_evolution` |
| 聊天室原生团队 | `facilitator`、`chat_planner`、`chat_coder`、`chat_reviewer`、`researcher`、`critic`、`scribe` |

`assistant` 负责对话协调与委派；`coder` 可通过 `write_file`、`edit_file`、`read_file` 等工具在工作区真实落盘；`reviewer` 负责六维度审查；`agent_manager` 通过白名单字段维护既有 Agent 的模型、Tools、Skills、MCP 和默认工作区配置，调用 `update_agent_config` 后直接热重载，审计依赖 `config_change` 日志和 git 追溯。

### 3. 聊天室协作团队

系统新增原生 Chatroom 模型，用来展示多 Agent 团队协作：

- `facilitator` 作为默认主持人，负责拆解目标、组织发言和收敛结论。
- `chat_planner`、`chat_coder`、`chat_reviewer`、`researcher`、`critic`、`scribe` 分别承担规划、实现、审查、研究、质疑和记录职责。
- 支持聊天室目标、待办、邀请、发言派发、取消 in-flight 发言任务。
- 聊天室可绑定 Project 工作区，Agent 文件工具会落到该工作区内。

这部分适合答辩现场展示“多智能体协作”本身，而不只是展示单个聊天机器人。

### 4. 项目工作区与文件安全边界

系统提供受管理的 Project 工作区：

- `POST /api/workspaces/import` 上传 zip 并导入到 `workspace/projects/{workspace_id}/`。
- `GET /api/workspaces`、`GET /api/workspaces/{id}`、`GET /api/workspaces/{id}/files` 查看工作区和文件树。
- `GET/PUT /api/workspaces/{id}/files/content` 读取或保存工作区内文本文件。
- Agent Run 的工作区优先级为：请求 `workspace_id` > 会话绑定 > Agent 默认工作区 > 自动 `workspace/runs/run-*`。
- 外部请求不能直接传可信 `workspace_root`，只通过后端解析出的工作区边界注入 Agent。

文件工具、附件 materialization、Artifact 和任务 transcript 都默认落在项目根目录下的 `./workspace`。

### 5. 能力库、Tools、Skills 与 MCP

当前 `config/capabilities.yaml` 注册 22 个能力：

| 类型 | 能力 |
|------|------|
| 代码与质量 | `code_parser`、`static_analyzer`、`test_runner` |
| 常用工具 | `memory_search`、`datetime_tool`、`calculator`、`web_fetch`、`web_search`、`json_tool`、`text_processor` |
| 文件与执行 | `file_search`、`read_file`、`write_file`、`edit_file`、`bash` |
| 生成与产物 | `create_frontend_artifact`、`requirement_checklist` |
| 系统进化 | `create_dynamic_tool_config`、`create_agent_config`、`read_agent_config`、`validate_agent_config_patch`、`update_agent_config` |

能力库 Catalog 已覆盖 Tools、Skills、MCP 三类资源：

- `GET /api/catalog/tools`、`GET /api/catalog/skills`、`GET /api/catalog/mcp`
- `POST /api/catalog/{kind}/{name}/assemble`
- `POST /api/catalog/{kind}/{name}/unassemble`

仓库内置 Skills 位于 `skills/`，包括 `systematic-debugging`、`test-driven-development`、`verification-before-completion`、`frontend-design`、`mcp-builder`、`pdf`、`docx` 等。核心 Agent 已预装推荐工程纪律 Skill。

MCP 支持已从“预留接口”推进到 Agent-scoped 配置与运行态代理：`config/mcp_servers.yaml` 提供 filesystem、git、fetch、sqlite 模板，均为 `stdio` 且默认禁用；当前 `config/agents.yaml` 未默认启用任何 MCP server。管理员可把模板装配到具体 Agent，运行态通过 adapter 注册 Agent 作用域代理工具，并进入 `proxy_available`、`partial` 或 `adapter_unavailable` 等可解释状态。

### 6. 长期记忆与人格系统

- 记忆后端默认 ChromaDB，缺依赖时可降级到 InMemory。
- 支持自动对话反思、结构化候选、去重巩固、遗忘、检索解释和访问记录更新。
- 记忆注入 Agent prompt 时明确标记为“不可信资料”，只能作为事实参考，不能覆盖系统规则。
- 人格系统支持定义、版本、绑定、归档、恢复、回滚和 pending 迭代建议。
- 新前端优先通过 `/api/agents/persona-bindings*` 管理 Agent/Session 人格绑定。

### 7. 附件、Artifact 与认证

- 附件 API 支持上传、列表、读取、删除，并可将非图片附件 materialize 到工作区 `.attachments/` 下供 Agent 读取。
- Artifact API 支持创建、列出、内容预览、下载、inline 打开和删除，默认存储在 `workspace/artifacts/`。
- 可选全局访问密码门禁：`server.access_password` 非空时，`/api/*` 需要 `Authorization: Bearer <token>`；`/api/health`、Swagger 文档和静态入口豁免。
- 认证失败带 IP 窗口计数和临时锁定；前端有 `LoginPage` 与 WebSocket token 透传。

## 系统架构

```
React / TypeScript 前端工作台
  | REST API + WebSocket
  v
FastAPI 服务层
  | routes + schemas + auth middleware + websocket handlers
  v
UnifiedBus 统一消息总线
  | event / request / broadcast / route / metrics
  v
运行时核心
  | Agent Run + TaskRegistry + transcript
  | CapabilityRegistry + Tools/Skills/MCP
  | Memory + Persona + Context + Workspace + Artifact
  v
配置化 Agent 层
  | assistant / planner / coder / reviewer / manager / chatroom team
  v
LLM 客户端
  | OpenAI-compatible / Anthropic + retry + streaming + tool use
```

## 目录结构

```
agentic-system/
├── config/
│   ├── agents.yaml              # 15 个 Agent 配置
│   ├── capabilities.yaml        # 22 个能力配置
│   ├── mcp_servers.yaml         # MCP 模板库
│   └── system.yaml              # 系统、LLM、记忆、工具、认证配置
├── backend/
│   ├── requirements.txt
│   ├── src/
│   │   ├── api/                 # FastAPI 路由、认证中间件、WebSocket
│   │   ├── capabilities/        # 内置工具能力
│   │   ├── core/                # Agent、Bus、Memory、Workspace、MCP、Task 等核心模块
│   │   └── utils/
│   └── tests/                   # 单元与集成测试
├── frontend/
│   ├── src/
│   │   ├── components/          # 工作台面板与通用组件
│   │   ├── api/                 # 前端 API client
│   │   ├── hooks/
│   │   ├── store/
│   │   ├── types/
│   │   └── utils/
│   └── tests/                   # 前端契约/逻辑测试
├── skills/                      # 本地 Skill 库
├── docs/                        # 架构、API、部署、设计与计划文档
├── workspace/                   # 运行时工作区、Artifact、transcript，本地忽略
├── AGENTS.md                    # 面向后续 AI 和开发者的架构说明
├── QUICKSTART.md
├── HANDOFF.md
└── README.md
```

## 前端工作台

当前前端已经从早期“9 个面板”升级为综合工作台：

| 页面 | 说明 |
|------|------|
| 总览 | 系统健康、运行时状态和关键入口 |
| 对话 | 单会话 Assistant 对话、附件、Markdown、工作区绑定 |
| 聊天室 | 多 Agent 原生协作房间，支持主持人、团队成员、目标和消息流 |
| 工作区 | Project 工作区导入、文件树、文件读取和编辑 |
| 智能体 | Agent 配置、Tools、Skills、MCP、模型、默认工作区与人格绑定 |
| 运行 | Agent Run 创建、列表、进度、输出和 transcript |
| 监控 | WebSocket 事件、Agent 进度和系统监控 |
| 记忆 | 记忆统计、搜索、创建、设置、巩固和遗忘 |
| 工具 | 能力库中 Tool 的浏览和装配 |
| Skills | 本地 Skill 库浏览和装配 |
| MCP | MCP 模板和 Agent-scoped MCP 配置 |
| 人格 | Persona 定义、版本、绑定、建议/历史归档与回滚 |
| 设置 | LLM、工具和系统配置热更新 |

## REST API 速览

| 模块 | 关键端点 |
|------|----------|
| 健康与配置 | `GET /api/health`、`GET/POST /api/config`、`POST /api/config/models` |
| Agent | `GET /api/agents`、`GET /api/agents/configs`、`GET /api/agents/{name}/config`、`POST /api/agents/{name}/invoke`、`POST /api/agents/{name}/mcp/import` |
| 人格绑定 | `GET /api/agents/persona-bindings`、`PUT/DELETE /api/agents/persona-bindings/agents/{agent_name}`、`PUT/DELETE /api/agents/persona-bindings/sessions/{session_id}` |
| Agent Run | `POST /api/runs`、`GET /api/runs`、`GET /api/runs/{run_id}`、`GET /api/runs/{run_id}/events`、`GET /api/runs/{run_id}/memory-context`、`POST /api/runs/{run_id}/control`、`GET /api/runs/workspaces` |
| 任务兼容入口 | `POST /api/tasks`、`GET /api/tasks`、`GET /api/tasks/{task_id}/transcript`、`DELETE /api/tasks/{task_id}` |
| 工作区 | `GET /api/workspaces`、`POST /api/workspaces/import`、`GET/DELETE /api/workspaces/{id}`、`GET /api/workspaces/{id}/files`、`GET/PUT /api/workspaces/{id}/files/content` |
| 聊天室 | `GET/POST /api/chatrooms`、`GET/PUT/DELETE /api/chatrooms/{id}`、`GET/POST /api/chatrooms/{id}/messages`、`POST /api/chatrooms/{id}/invoke`、`POST /api/chatrooms/{id}/cancel` |
| 会话与附件 | `GET/POST /api/chat-sessions`、`POST /api/chat-sessions/{id}/messages`、`GET/POST /api/attachments`、`GET /api/attachments/{id}/content` |
| 记忆 | `GET /api/memory/stats`、`GET /api/memory/list`、`POST /api/memory/search`、`POST /api/memory/create`、`POST /api/memory/consolidate`、`POST /api/memory/forget` |
| 能力库 | `GET /api/catalog/tools`、`GET /api/catalog/skills`、`GET /api/catalog/mcp`、`POST /api/catalog/{kind}/{name}/assemble`、`POST /api/catalog/{kind}/{name}/unassemble` |
| Artifact | `GET/POST /api/artifacts`、`GET /api/artifacts/{id}`、`GET /api/artifacts/{id}/content`、`GET /api/artifacts/{id}/download`、`GET /api/artifacts/{id}/open` |
| 进化中心 | `GET /api/evolution/system-status`、`POST /api/evolution/command`、`GET/PUT /api/evolution/tool-prompts/{name}`、`POST /api/evolution/reload` |

完整 API 说明见 [docs/api.md](docs/api.md)。

## 安装与启动

### 环境要求

- Python 3.10+
- Node.js 18+
- npm

### 后端

```bash
cd backend
pip install -r requirements.txt
cd src
uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

也可以在 `backend/src` 下运行：

```bash
python -m api.main
```

后端默认地址：`http://127.0.0.1:8001`。

### LLM 配置

建议使用 `backend/src/config.yaml` 或环境变量。`backend/src/config.yaml` 已被 `.gitignore` 忽略，不应提交真实密钥。

```yaml
llm:
  provider: "openai"
  model: "gpt-5.5"
  api_key: "your-api-key"
  base_url: "https://example-compatible-endpoint/v1"
```

环境变量覆盖：

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-your-key
export LLM_MODEL=gpt-5.5
export LLM_BASE_URL=https://example-compatible-endpoint/v1
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认地址：`http://localhost:3000`。

### 常用入口

| 地址 | 说明 |
|------|------|
| `http://localhost:3000` | 前端工作台 |
| `http://localhost:8001/docs` | Swagger 文档 |
| `http://localhost:8001/api/health` | 健康检查 |
| `ws://localhost:8001/ws` | WebSocket 实时事件 |

## 答辩演示建议

推荐演示路径：

1. 打开“总览”说明系统健康、Agent 数量、工作区和运行态。
2. 在“工作区”导入一个小项目 zip，展示 `workspace_id` 和文件树。
3. 在“运行”创建 `coder` Agent Run，让它在指定工作区生成或修改项目文件。
4. 展开 transcript，展示 `thinking`、`tool_call`、`write_file`、`reviewer` 审查和 `done` 输出。
5. 切到“聊天室”，创建带 `facilitator` 的协作房间，展示规划者、编码者、审查者、研究员、批评者、记录员的团队协作。
6. 切到“智能体 / Skills / MCP / 工具”，说明系统可以运行时装配能力，而不是写死在代码里。
7. 切到“记忆 / 人格”，说明系统支持长期偏好、反思和人格配置，但都以“不可信资料”和管理员审核边界注入。

一个适合现场的真实 demo 是“智能课程作业批改助手”或“需求文档转测试用例工具”：让 Agent 在工作区内生成小型 FastAPI 项目、测试和 README，再由 reviewer 审查，最后用 transcript 证明过程可追溯。

## 测试与验证

后端：

```bash
python -m pytest backend/tests/ -q
python -m pytest backend/tests/unit/ -v
python -m pytest backend/tests/integration/ -v
```

前端：

```bash
cd frontend
npm run test
npm run build
```

真实 API 冒烟验证：

```bash
python tests/api_live_test.py --suite infra
python tests/api_live_test.py --suite smoke
```

Windows 终端遇到中文显示问题时可设置：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

## 当前项目统计

| 指标 | 当前值 |
|------|--------|
| 后端 Python 源文件 | 118 |
| 后端测试文件 | 73 |
| 前端 TS/TSX 文件 | 30 |
| 前端 CSS 文件 | 21 |
| Agent 配置 | 15 |
| Capability 配置 | 22 |
| 本地 Skills | 12 |
| 主配置文件 | `agents.yaml`、`capabilities.yaml`、`mcp_servers.yaml`、`system.yaml` |

这些数字来自当前工作树文件扫描，不再沿用旧 README 中的 4 Agent、9 面板、605 用例口径。

## 关键文档

- [AGENTS.md](AGENTS.md)：面向后续 AI 和开发者的详细架构说明。
- [QUICKSTART.md](QUICKSTART.md)：快速启动与演示。
- [HANDOFF.md](HANDOFF.md)：交接说明与维护入口。
- [docs/api.md](docs/api.md)：完整 API 文档。
- [docs/architecture.md](docs/architecture.md)：架构设计说明。
- [docs/deployment.md](docs/deployment.md)：部署说明。
- [docs/superpowers/specs/](docs/superpowers/specs/)：近期开关、聊天室、能力库、工作区等设计文档。
- [docs/superpowers/plans/](docs/superpowers/plans/)：对应实施计划。
