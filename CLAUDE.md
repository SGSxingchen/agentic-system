# CLAUDE.md — 当前项目说明入口

**版本:** v2.7
**日期:** 2026-06-02
**状态:** 本文件已不再维护独立架构正文，避免与 `AGENTS.md` 形成两份互相漂移的项目说明。

当前权威架构文档是：

- `AGENTS.md`：面向后续 AI 和开发者的完整架构、模块、API、配置和开发规范。
- `README.md`：面向用户、评审和答辩展示的项目概览。
- `QUICKSTART.md`：本地启动与演示步骤。
- `HANDOFF.md`：交接清单、关键文件和已知边界。
- `docs/api.md`：REST / WebSocket API 说明。
- `docs/architecture.md`：系统分层、运行模型和数据流。
- `docs/deployment.md`：本地运行、配置、部署和访问密码说明。

## 当前主线摘要

系统已经从早期固定 Pipeline 迁移为 **Agent Run + Project 工作区 + 能力库 + 聊天室协作团队** 的运行时：

- `config/agents.yaml` 当前配置 15 个 Agent，包含核心协作、系统管理和聊天室原生协作团队。
- `config/capabilities.yaml` 当前配置 22 个能力。
- `skills/` 内置 12 个 Skill，可通过能力库装配到指定 Agent。
- `config/mcp_servers.yaml` 提供 filesystem、git、fetch、sqlite MCP 模板，默认禁用，可按 Agent 装配。
- 前端工作台包含总览、对话、聊天室、工作区、智能体、运行、监控、记忆、工具、Skills、MCP、人格和设置。

## 不再使用的旧口径

不要再把当前系统描述为：

- 4 个硬编码 Agent。
- 固定 plan -> code -> review Pipeline。
- `/api/pipelines/*` 或 `config/pipelines.yaml`。
- 旧 `TaskPanel`、旧 `EvolutionPanel` 或“一键 Demo”主流程。
- MCP 仅预留接口。

详细规范请以 `AGENTS.md` 为准。
