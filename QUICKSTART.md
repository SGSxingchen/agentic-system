# 快速开始

> 5 分钟启动多智能体代码生成与审查系统

## 前置要求

- Python 3.10+
- Node.js 18+
- pip / npm

## 1. 安装依赖

```bash
# 后端
cd backend
pip install -r requirements.txt

# 前端
cd ../frontend
npm install
```

## 2. 配置 LLM

编辑 `backend/src/config.yaml`：

```yaml
llm:
  provider: "openai"             # openai / anthropic
  model: "gpt-4"                 # 模型名称
  api_key: "your-api-key-here"   # API Key
  base_url: ""                   # 自定义端点 (可选)
```

或使用环境变量：

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-your-key
export LLM_MODEL=gpt-4
```

也可以启动后在前端 Settings 面板中配置（支持热重载）。

## 3. 启动

### 后端 (端口 8001)

```bash
cd backend/src
uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

### 前端 (端口 3000)

```bash
cd frontend
npm run dev
```

## 4. 访问

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | 前端界面 |
| http://localhost:8001/docs | Swagger API 文档 |
| http://localhost:8001/api/health | 健康检查 |
| ws://localhost:8001/ws | WebSocket 实时通信 |

## 5. 使用

1. **对话** — 在 ChatPanel 输入消息，AssistantAgent 自动回复（带记忆检索）
2. **答辩 Demo** — 在“运行 / Agent Run 答辩演示台”点击一键 Demo，快速创建小型 Flask API、Python 工具函数或 CSV 数据处理脚本任务
3. **Run 时间线** — 展开 Agent Run，查看 run_id、agent、workspace、status、耗时、流式生成片段和 transcript 事件
4. **最终输出** — Run 完成后展开最终输出，查看生成代码、运行命令、测试/验收说明
5. **提交任务** — 也可以在 TaskPanel 手动描述需求，创建自定义 Agent Run
6. **查看智能体** — 在 AgentPanel 查看各 Agent 的状态和能力
7. **工作流** — 在 WorkflowPanel 选择预设模板执行代码生成任务（兼容旧流程）
8. **记忆管理** — 在 MemoryPanel 查看/搜索/创建/删除记忆
9. **系统监控** — 在 MonitorPanel 查看实时系统状态

答辩材料图、讲稿和兜底方案见 `docs/demo/DEFENSE_MATERIALS.md`；Demo 验收步骤见 `docs/demo/DEMO_ACCEPTANCE_2026-05-11.md`。

## 6. 运行测试

```bash
# 全部测试 (~331 个用例)
python3 -m pytest backend/tests/ -q

# 单元测试
python3 -m pytest backend/tests/unit/ -v

# 集成测试
python3 -m pytest backend/tests/integration/ -v

# 真实 LLM 冒烟验证（需先启动后端）
python3 tests/api_live_test.py --suite smoke

# 真实 LLM 全量 API 验证
python3 tests/api_live_test.py
```

Windows 终端如遇 emoji/编码问题，可先设置：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

## 核心架构

```
用户 → 前端 (React) → WebSocket / REST → FastAPI
                                            ↓
                                    UnifiedBus (消息总线)
                                    ↙    ↓    ↘
                            Planner  Coder  Reviewer
                               ↓       ↓       ↓
                             计划  →  代码  →  审查 → 完成
```

## 功能速览

- ✅ 4 个专业智能体 (Assistant / Planner / Coder / Reviewer)
- ✅ 统一消息总线 (发布订阅 / 请求响应 / 广播 / 优先级队列)
- ✅ 事件引擎 + 扳机系统 (ECA 规则引擎)
- ✅ 工作流编排 (顺序 / 并行 / 条件 / 重试 / YAML 模板)
- ✅ 长期记忆系统 (情景/语义/程序记忆 + 多信号加权检索)
- ✅ 能力插件 (代码解析 / 静态分析 / 测试运行)
- ✅ 上下文管理 (全局/会话/智能体三层作用域)
- ✅ 19 个 REST API + WebSocket 实时通信
- ✅ React 前端 (8 个面板)
- ✅ ~331 个测试用例 (单元 + 集成)
- ✅ YAML 配置体系 (5 个配置文件 + 动态加载 + fallback)
- ✅ 结构化日志 + 链路追踪

## 更多文档

- 架构详情 → `CLAUDE.md`
- API 文档 → `docs/api.md`
- 部署指南 → `docs/deployment.md`
- 交接文档 → `HANDOFF.md`
