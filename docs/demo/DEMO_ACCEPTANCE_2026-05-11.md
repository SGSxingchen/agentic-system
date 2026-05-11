# 答辩 Demo 验收说明（2026-05-11）

目标：让答辩现场能在 1 分钟内启动一个清晰、可观测、老师易理解的 Agent Run，展示“多智能体协作 + 工具调用 + 记忆上下文 + transcript 可观测性”。

## 推荐演示入口

前端进入 **运行 / Agent Run 答辩演示台**，使用页面顶部「一键预设任务」。

推荐顺序：

1. **小型 Flask API**（最适合答辩）
   - 生成 `app.py`、`/health`、`/todos GET/POST`、运行命令和 curl 示例。
   - 讲解点：需求理解、代码生成、验收命令清晰。
2. **Python 工具函数**（快速稳定）
   - 生成函数、示例输入输出和 pytest 用例。
   - 讲解点：输出短、边界条件和测试容易说明。
3. **CSV 数据处理脚本**（体现工具链）
   - 生成清洗脚本、示例 CSV、输出说明。
   - 讲解点：脚本化任务、数据处理流程、最终结果可复盘。

## 现场操作脚本

1. 确认后端 `8001`、前端 `3001` 在线。
2. 打开前端 → 侧边栏 **运行**。
3. 点击「小型 Flask API」卡片中的 **一键演示**。
4. 展开刚创建的 Run：
   - 顶部应显示 `run_id`、`agent`、`status`、`workspace`、耗时。
   - `Transcript 时间线` 应按顺序展示 `created`、`started`、流式生成片段（底层事件名为 `thinking`）、`tool_call/tool_result`（如有）、`done/error/killed`。
   - 每个事件都可以展开查看原始 payload。
5. Run `completed` 后展开 **最终输出**，展示生成代码、运行命令和说明。

## API 兼容验收

本轮只增强前端展示，不破坏现有后端接口：

- `POST /api/tasks`：旧任务入口仍可用，默认 `pipeline=auto` 会进入 Agent Run 兼容模式。
- `GET /api/tasks/{id}`：仍返回任务详情、状态、进度和输出。
- `GET /api/tasks/{id}/transcript`：仍读取落盘 JSONL transcript。
- 前端 Run 页面当前使用 `GET /api/runs/{id}/events` 读取同一 transcript 数据源。

## 通过标准

- 点击任一预设任务后，页面无需手写 prompt 即可提交 Run。
- Run 列表能看到清晰的目标、Agent、Workspace、Status、耗时。
- 展开 Run 后能看懂时间线，不再只有大段 JSON。
- completed 后可以展开最终输出用于答辩讲解。
- 空状态文案明确强调多智能体、记忆、工具和可观测性，而不是普通聊天网页。

## 验证命令

```bash
cd frontend
npm run build
```

如本轮修改后端，再运行：

```bash
python3 -m pytest backend/tests/ -q
```
