# HANDOFF.md — 项目交接文档

> 最后更新: 2026-06-02
> 本文档按 `db26ae4..HEAD` 提交追溯同步，面向后续 AI 或开发者快速接手当前主分支。

## 1. 当前状态

总体评估：核心功能可运行、可演示，系统已经从早期固定 Pipeline 迁移为 **Agent Run + Project 工作区 + 能力库 + 聊天室协作团队** 的运行时。

- 后端 FastAPI、WebSocket、Agent Run、工作区、记忆、人格、附件、Artifact、能力库、聊天室等 API 已实现。
- 当前 `config/agents.yaml` 配置 15 个 Agent。
- 当前 `config/capabilities.yaml` 配置 22 个能力。
- 仓库内置 12 个 Skill，可通过能力库装配到指定 Agent。
- `config/mcp_servers.yaml` 提供 filesystem、git、fetch、sqlite 四个 stdio MCP 模板，默认禁用；Agent 可按需挂载。
- 前端已改为工作台形态：总览、对话、聊天室、工作区、智能体、运行、监控、记忆、工具、Skills、MCP、人格、设置。
- 可选全局访问密码已接入：`server.access_password` 非空时 `/api/*` 使用 Bearer token，WebSocket 使用 `?token=`。

## 2. 当前关键能力

### 核心运行时

- UnifiedBus：发布/订阅、请求/响应、点对点、广播、优先级队列、消息历史和运行指标。
- Agent Run：每次运行拥有独立 `run_id/task_id`、Agent、Session、Workspace、目标、状态、进度、输出和 transcript。
- TaskRegistry + TranscriptWriter：运行状态和事件 JSONL 落盘，`/api/runs/{id}/events` 可读取。
- CapabilityRegistry：统一管理原生工具、动态 Tool、Agent-as-Tool、MCP 代理工具。
- WorkspaceStore：Project zip 导入、manifest、文件树、文本读写、安全路径校验。
- ArtifactStore：HTML、Markdown、代码、图片、文件等产物预览/下载/打开。

### Agent

| 分组 | Agent |
|------|-------|
| 核心协作 | `assistant`、`planner`、`coder`、`reviewer` |
| 系统管理 | `tool_creator`、`agent_creator`、`agent_manager`、`persona_evolution` |
| 聊天室团队 | `facilitator`、`chat_planner`、`chat_coder`、`chat_reviewer`、`researcher`、`critic`、`scribe` |

### 前端

- 已删除旧 `TaskPanel` 和旧 `EvolutionPanel`。
- 运行入口是 `RunsPanel`。
- 能力相关入口拆为 `ToolsPanel`、`SkillsPanel`、`McpPanel`。
- 新增 `WorkspacePanel`、`ChatroomPanel`、`OverviewPanel`、`LoginPage`、`Topbar`。

### 安全和边界

- `bash` 能力存在但默认关闭，需显式开启 `ENABLE_SHELL_TOOL=true` 或配置 `tools.shell.enabled=true`。
- 文件工具默认工作区为 `./workspace`，Run 会通过可信 `_trusted_workspace_root` 注入当前工作区。
- 工作区 zip 导入会拒绝 zip-slip、绝对路径、`..`、Windows 保留名等不安全路径。
- 记忆、附件、网页、文件、工具结果都应作为不可信资料注入 Agent prompt。
- Agent 配置写入由 `agent_manager` 的白名单字段控制，`update_agent_config` 调用即生效并写 `config_change` 审计日志。

## 3. 关键文件索引

| 目标 | 关键文件 |
|------|----------|
| 应用入口/初始化 | `backend/src/api/main.py` |
| 路由聚合 | `backend/src/api/routes/__init__.py` |
| Agent Run / Task | `backend/src/api/routes/tasks.py`、`backend/src/core/task/` |
| Agent 配置 API | `backend/src/api/routes/agents.py` |
| 工作区 | `backend/src/api/routes/workspaces.py`、`backend/src/core/workspace.py` |
| 聊天室 | `backend/src/api/routes/chatrooms.py`、`backend/src/core/chatroom.py`、`backend/src/core/chatroom_orchestrator.py` |
| 附件 | `backend/src/api/routes/attachments.py`、`backend/src/core/attachment*.py` |
| Artifact | `backend/src/api/routes/artifacts.py`、`backend/src/core/artifacts.py` |
| 能力库 | `backend/src/api/routes/catalog.py` |
| MCP | `backend/src/core/mcp.py`、`backend/src/core/mcp_adapter.py`、`backend/src/core/mcp_import.py`、`config/mcp_servers.yaml` |
| Agent 配置 | `config/agents.yaml` |
| 能力配置 | `config/capabilities.yaml` |
| 系统配置 | `config/system.yaml` |
| 前端入口 | `frontend/src/App.tsx` |
| 前端 API | `frontend/src/api/client.ts` |
| 前端状态 | `frontend/src/store/appStore.tsx` |
| 前端面板 | `frontend/src/components/` |

## 4. 常用启动命令

后端：

```bash
cd backend/src
uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

前端：

```bash
cd frontend
npm run dev
```

## 5. 常用测试命令

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

真实 API 冒烟：

```bash
python tests/api_live_test.py --suite infra
python tests/api_live_test.py --suite smoke
```

## 6. 当前项目统计

| 指标 | 当前值 |
|------|--------|
| 后端 Python 源文件 | 118 |
| 后端测试文件 | 73 |
| 前端 TS/TSX 文件 | 30 |
| 前端 CSS 文件 | 21 |
| Agent 配置 | 15 |
| Capability 配置 | 22 |
| 本地 Skills | 12 |
| REST route decorators | 约 100 个，完整列表以 `backend/src/api/routes/` 为准 |

## 7. 已知注意事项

- `workspace/`、`data/`、`backend/src/config.yaml` 都是本地运行态或密钥相关内容，不应提交。
- README、QUICKSTART、AGENTS、docs/architecture 和 docs/api 需要随架构变动同步。
- 前端真实 UI 不再有“一键 Demo”按钮，不要在答辩材料中沿用旧说法。
- MCP 当前有模板库和 Agent-scoped adapter 支持，但默认没有 Agent 启用 MCP server；演示时应说“可配置/可装配”，不要说“默认已经连接外部 MCP”。
- 聊天室适合演示多 Agent 协作，但更准确的表述是“支持 host、@ 成员、目标/Todo 和协作调度事件”，不要夸成完全自动项目经理。
