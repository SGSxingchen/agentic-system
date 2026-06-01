# 快速开始

> 5 分钟启动当前版多智能体代码生成与审查系统
> 同步时间: 2026-06-02

## 1. 环境要求

- Python 3.10+
- Node.js 18+
- npm

## 2. 安装依赖

```bash
# 后端
cd backend
pip install -r requirements.txt

# 前端
cd ../frontend
npm install
```

## 3. 配置 LLM

推荐把本地密钥写入 `backend/src/config.yaml`，该文件已被 `.gitignore` 忽略。

```yaml
llm:
  provider: "openai"
  model: "gpt-5.5"
  api_key: "your-api-key"
  base_url: "https://your-openai-compatible-endpoint/v1"
```

也可以使用环境变量：

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-your-key
export LLM_MODEL=gpt-5.5
export LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
```

如果配置了 `server.access_password`，前端会先进入登录页；后端 `/api/*` 请求需要 `Authorization: Bearer <token>`。

## 4. 启动

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

## 5. 访问入口

| 地址 | 说明 |
|------|------|
| `http://localhost:3000` | 前端工作台 |
| `http://localhost:8001/docs` | Swagger API 文档 |
| `http://localhost:8001/api/health` | 健康检查 |
| `ws://localhost:8001/ws` | WebSocket 实时事件 |

## 6. 当前推荐演示流程

1. 在“总览”页确认后端健康、WebSocket 状态和最近运行。
2. 在“工作区”页导入一个 zip 项目，得到受管理的 `workspace_id`。
3. 在“运行”页选择 `coder` 或 `assistant`，绑定工作区并创建 Agent Run。
4. 展开运行详情，查看 transcript、工具调用、输出和错误状态。
5. 在“聊天室”页创建多 Agent 房间，用 `facilitator`、`chat_planner`、`chat_coder`、`chat_reviewer` 等展示协作。
6. 在“工具 / Skills / MCP / 智能体”页展示能力库装配、Agent 配置、默认工作区和 MCP 模板。
7. 在“记忆 / 人格”页展示长期记忆、人格绑定、版本和审核式迭代。

注意：当前前端不再使用旧 `TaskPanel` 和 `EvolutionPanel`；运行入口是 `RunsPanel`，能力入口拆分为 Tools、Skills、MCP。

## 7. 常用 API

```bash
# 健康检查
curl http://127.0.0.1:8001/api/health

# 创建 Agent Run
curl -X POST http://127.0.0.1:8001/api/runs \
  -H "Content-Type: application/json" \
  -d '{"goal":"生成一个小型 Python CLI 项目","agent_name":"coder","auto_memory":false}'

# 查询运行详情
curl http://127.0.0.1:8001/api/runs/<run_id>

# 查询运行事件流
curl http://127.0.0.1:8001/api/runs/<run_id>/events
```

## 8. 测试

后端：

```bash
python -m pytest backend/tests/ -q
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

Windows 终端遇到中文显示问题时可设置：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

## 9. 当前能力速览

- 15 个配置化 Agent，包括核心 assistant/planner/coder/reviewer、系统管理 Agent 和聊天室原生团队。
- 22 个能力配置，包括代码解析、测试运行、文件读写、编辑、Web、Artifact、Agent 管理等。
- Agent Run 多实例调度，支持 session/workspace/agent 维度隔离和 transcript 事件流。
- Project 工作区导入、文件树、文本读取/编辑和 Agent 工具边界。
- Tools / Skills / MCP 能力库装配与卸下。
- 附件、Artifact、长期记忆、人格系统和可选全局访问密码。

更多细节见 `README.md`、`AGENTS.md`、`docs/api.md`、`docs/architecture.md`。
