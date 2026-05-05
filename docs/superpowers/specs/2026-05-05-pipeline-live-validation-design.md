# Pipeline Live Validation Design

> 日期: 2026-05-05
> 范围: live 验收脚本与项目文档同步

## 背景

当前代码已完成 Workflow 到 Pipeline 的迁移：后端主路由是 `/api/pipelines/*`，配置文件是 `config/pipelines.yaml`，前端面板是 `PipelinePanel`。但部分文档和 `tests/api_live_test.py` 仍引用旧的 `/api/workflows/*`、`workflow` 字段和 WorkflowPanel 术语。

这会影响两个场景：

- 答辩或演示前运行 live 验收脚本时，旧接口会直接返回 404。
- 后续接手者按 README/HANDOFF/API 文档操作时，会得到与当前代码不一致的路径和概念。

## 目标

让本地验收入口和文档以 Pipeline 为准，并提供一个不依赖 LLM API Key 的快速基础设施验收套件。

## 设计

### API 验收脚本

`tests/api_live_test.py` 保留 `smoke` 和 `full` 套件，同时新增 `infra` 套件。

- `infra` 只访问确定性端点：`/api/health`、`/api/config`、`/api/agents`、`/api/pipelines/templates` 和一个无效 Pipeline 执行错误路径。
- `smoke` 继续包含 Agent/Pipeline 执行链路，但所有 Workflow 路径改为 `/api/pipelines/*`。
- 请求体字段统一使用 `template_name`、`pipeline_type`、`requirement`、`options`。

### 测试策略

新增单元测试覆盖 live 脚本本身：

- 确认 `run_smoke_tests()` 不再请求 `/api/workflows/*`。
- 确认新增 `run_infra_tests()`，且它只使用快速、非 LLM 的端点。

### 文档同步

更新主要接手文档中的旧术语：

- `README.md`
- `HANDOFF.md`
- `docs/api.md`

同步重点是路径、配置文件名、面板名和运行命令。架构深度文档中已经标记 Phase B/C 已落地，本轮只修正会误导运行和验收的直接说明。

## 非目标

- 不恢复 `/api/workflows/*` 兼容路由。
- 不改 Pipeline 执行器核心逻辑。
- 不引入前端测试框架。
- 不处理浏览器插件的 Node REPL 版本问题，只在最终结果中记录该环境阻塞。

## 验收

- `backend/.venv/Scripts/python.exe -m pytest backend/tests/ -q`
- `npm run build` in `frontend/`
- `backend/.venv/Scripts/python.exe tests/api_live_test.py --suite infra`
