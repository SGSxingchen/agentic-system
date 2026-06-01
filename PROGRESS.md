# 毕设项目进度追踪

**最后更新:** 2026-06-02
**当前状态:** 可演示、可继续扩展
**同步依据:** 已按 `db26ae4..HEAD` 提交追溯，覆盖工作区、Agent Run、聊天室、能力库、MCP、附件、Artifact、认证和前端工作台变更。

## 开发铁律

所有新功能或架构改动继续遵循：

1. 先扩充文档：在 `AGENTS.md`、`docs/architecture.md`、`docs/api.md` 或相关设计文档中说明功能边界。
2. 按文档编码：实现必须与文档中的 API、配置、权限边界一致。
3. 可行性验收：至少运行相关后端测试、前端测试或构建；涉及演示链路时补充 API 冒烟验证。

## 当前统计

| 指标 | 当前值 |
|------|--------|
| 后端 Python 源文件 | 118 |
| 后端测试文件 | 73 |
| 前端 TS/TSX 文件 | 30 |
| 前端 CSS 文件 | 21 |
| REST route decorators | 98 |
| Agent 配置 | 15 |
| Capability 配置 | 22 |
| 本地 Skill | 12 |
| 主配置文件 | `agents.yaml`、`capabilities.yaml`、`mcp_servers.yaml`、`system.yaml` |

## 已完成主线

| 模块 | 状态 | 说明 |
|------|------|------|
| UnifiedBus | 已完成 | 发布/订阅、请求/响应、路由、广播、优先级队列、历史和指标 |
| Agent Run | 已完成 | `/api/runs` 多实例调度，支持 session/workspace/agent 隔离、transcript、取消/暂停/继续 |
| Project 工作区 | 已完成 | zip 导入、manifest、文件树、文本读写、Run/Session/Agent 工作区解析 |
| 配置化 Agent | 已完成 | `config/agents.yaml` 当前 15 个 Agent，含核心协作、系统管理和聊天室团队 |
| 能力系统 | 已完成 | 22 个能力配置，支持原生 Tool、Agent-as-Tool、动态 Tool、Catalog 装配/卸下 |
| Skills | 已完成 | `skills/` 内置 12 个 Skill，核心 Agent 已挂载推荐工程纪律 Skill |
| MCP | 部分完成 | Agent-scoped 配置、模板库和 stdio adapter 已接入；模板默认禁用，按 Agent 装配 |
| 长期记忆 | 已完成 | ChromaDB 默认持久化，InMemory 降级，自动反思、召回解释、巩固和遗忘 |
| 人格系统 | 已完成 | Persona 定义、版本、归档/恢复、回滚、绑定和建议审核 |
| 聊天室协作 | 已完成 | facilitator + 6 个 text Agent，支持目标、Todo、@ 成员派发、取消和工作区绑定 |
| 附件与 Artifact | 已完成 | 附件上传/读取/删除，Artifact 创建、预览、下载、inline 打开 |
| 全局访问密码 | 已完成 | `server.access_password`、Bearer token、WebSocket token 和失败锁定 |
| 前端工作台 | 已完成 | 总览、对话、聊天室、工作区、智能体、运行、监控、记忆、工具、Skills、MCP、人格、设置 |

## 最近追溯到的提交主题

- OpenAI 兼容接口地址规范化。
- Project 工作区与 Agent 模型/工作区配置。
- 前端工作台合并并对齐后端接口。
- MCP 配置导入、Agent-scoped Skills/MCP 和运行态 adapter。
- 对话 markdown、侧栏收起、Agent prompt 自由化。
- 多 Agent 聊天室、协作调度、Todo、native text team 和 facilitator 默认 host。
- 能力库 Tools / Skills / MCP 浏览、装配和卸下。
- 文件工具、PDF 读取、pypdf 依赖和工具健壮性。
- 会话历史、聊天流式占位、滚动卡死等对话体验修复。

## 当前演示建议

1. 打开总览页确认后端健康、WebSocket 状态和系统概览。
2. 在工作区页导入一个小项目 zip，展示 `workspace_id`、文件树和边界校验。
3. 在运行页创建 `coder` 或 `assistant` Agent Run，绑定工作区并展示 transcript、工具调用和结果。
4. 在聊天室页创建带 `facilitator` 的协作房间，展示规划、编码、审查、研究、质疑、记录等角色协作。
5. 在工具 / Skills / MCP / 智能体页面展示运行时能力装配，而不是硬编码固定流水线。
6. 在记忆 / 人格页面展示长期偏好、反思、人格绑定和审核边界。

## 已知边界

- 固定 Pipeline、`/api/pipelines/*`、`config/pipelines.yaml`、旧 `TaskPanel` 和旧 `EvolutionPanel` 已不是现行主线。
- `MCP` 模板和 Agent-scoped adapter 已有，但默认没有 Agent 启用外部 MCP server；答辩时应表述为“可配置、可装配”。
- `bash` 能力存在但默认关闭，演示真实写文件优先使用受工作区边界约束的 `write_file` / `edit_file`。
- `workspace/`、`data/`、`backend/src/config.yaml` 是本地运行态或密钥相关内容，不应提交。

## 文档同步状态

本轮应保持同步的公开文档：

- `README.md`
- `QUICKSTART.md`
- `HANDOFF.md`
- `AGENTS.md`
- `CLAUDE.md`
- `docs/api.md`
- `docs/architecture.md`
- `docs/deployment.md`

历史设计文档保留原始演进记录，但凡涉及旧 Pipeline / 一键 Demo / TaskPanel 的内容，必须明确标注为历史阶段，不作为当前答辩口径。
