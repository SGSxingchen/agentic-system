# HANDOFF.md — 项目交接文档

> 最后更新: 2026-05-05
> 本文档帮助后续 AI 或人类开发者快速接手项目。

---

## 1. 项目当前状态

**总体评估: 核心功能已完成，可演示运行。**

- ✅ 后端 API 全部实现 (含进化中心 REST 端点 + WebSocket)
- ✅ 4 个智能体可工作 (需要有效的 LLM API Key)
- ✅ 前端 9 个面板全部可用
- ✅ 测试套件 605 个用例通过
- ✅ YAML 配置体系完整
- ✅ 支持运行时装载动态 Tool，并挂载到主 Agent/子 Agent
- ✅ 文档体系完整

---

## 2. 已完成功能清单

### 核心系统
- [x] UnifiedBus 统一消息总线 (发布/订阅、请求/响应、广播、优先级队列)
- [x] AgentRegistry + AgentLifecycleManager 智能体管理
- [x] Pipeline 编排 (顺序/并行/条件/超时/YAML 模板)
- [x] TaskRegistry + TranscriptWriter 任务状态和事件落盘
- [x] ContextStore 上下文管理 (全局/会话/智能体三层)
- [x] CapabilityRegistry 能力注册中心

### 智能体
- [x] AssistantAgent — 对话助手 (LLM + 记忆检索)
- [x] PlannerAgent — 任务规划 (需求 → 子任务 JSON)
- [x] CoderAgent — 代码生成 (结构化 JSON 输出)
- [x] ReviewerAgent — 代码审查 (六维度评估)

### 记忆系统
- [x] InMemoryStore + ChromaStore 双后端
- [x] MemoryFormation (创建/巩固/遗忘)
- [x] MemoryRetriever (多信号加权检索)
- [x] 记忆 REST API (CRUD + 搜索 + 巩固 + 遗忘)

### 能力插件
- [x] CodeParserCapability (AST 解析)
- [x] StaticAnalyzerCapability (代码质量检查)
- [x] TestRunnerCapability (测试运行)

### 前端
- [x] ChatPanel + AgentPanel + TaskPanel + PipelinePanel + EvolutionPanel
- [x] MemoryPanel + MonitorPanel + Settings + Sidebar
- [x] WebSocket 实时通信
- [x] 深色主题 UI

### 配置
- [x] config/agents.yaml + pipelines.yaml + capabilities.yaml + system.yaml
- [x] load_yaml_configs() 动态加载 + fallback 机制
- [x] 环境变量覆盖
- [x] 前端热重载配置

---

## 3. 已知问题和限制

### 架构层面
- **单进程限制**: 使用内存队列和内存存储，不支持多 worker 部署
- **SimpleBus 残留**: `core/bus/simple_bus.py` 仍存在，用于兼容旧测试和旧接口语义；运行时主总线为 UnifiedBus
- **两套能力实现**: `core/capability/native.py` (简化版) 和 `capabilities/builtin/` (完整版) 并存

### 功能层面
- **MCP 集成**: 仅预留接口，未实际实现
- **消息持久化**: 仅内存，无落盘
- **ChromaDB**: 可选依赖，默认使用内存后端
- **用户认证**: 无鉴权机制
- **速率限制**: 无 API 速率限制
- **前端测试**: 无前端自动化测试

### 已知 Bug
- Pipeline 执行的中间结果主要通过任务 transcript 和监控事件呈现，前端仍可继续增强步骤级实时详情展示

---

## 4. 下一步可以做的事

### 高优先级
1. **端到端集成验证**: 从前端提交任务 → 后端处理 → WebSocket 推送 → 前端显示，验证整条链路
2. **Demo 流程准备**: 准备毕业设计答辩演示脚本
3. **example_simple.py 完善**: 确保独立脚本可直接运行演示

### 中优先级
4. **统一能力实现**: 合并 `core/capability/native.py` 和 `capabilities/builtin/` 为一套
5. **统一本地演示脚本**: 将答辩演示脚本固定到 `tests/api_live_test.py --suite infra/smoke`
6. **前端实时 Pipeline 详情**: Pipeline 执行过程中展示步骤级输入、输出、耗时和错误
7. **前端自动化测试**: 为 9 个面板补 Vitest + React Testing Library 基础用例

### 低优先级
8. **MCP 客户端**: 实现真正的 MCP 协议集成
9. **消息持久化**: Redis 或 SQLite 后端
10. **用户认证**: JWT 或 API Key 鉴权
11. **性能优化**: 缓存 LLM 响应、连接池
12. **前端测试**: Vitest + React Testing Library

---

## 5. 关键文件索引

> 改什么看什么

| 要改的功能 | 需要看的文件 |
|-----------|-------------|
| 添加新 Agent | `core/agent/base.py` → `agents/*.py` → `config/agents.yaml` → `main.py._AGENT_CLASS_MAP` |
| 修改 Pipeline 事件流 | `backend/src/core/pipeline/pipeline.py` → `backend/src/api/routes/tasks.py` → `frontend/src/components/MonitorPanel.tsx` |
| 新增 API 端点 | `api/routes/*.py` → `api/schemas.py` → `api/routes/__init__.py` |
| 修改前端面板 | `frontend/src/components/*.tsx` + `*.css` |
| 配置变更 | `core/config.py` → `config/*.yaml` → `backend/src/config.yaml` |
| 添加能力插件 | `core/capability/native.py` → `config/capabilities.yaml` → `main.py._CAPABILITY_CLASS_MAP` |
| Pipeline 模板 | `config/pipelines.yaml` → `backend/src/core/pipeline/pipeline.py` → `backend/src/api/routes/pipelines.py` |
| 记忆系统 | `core/memory/` (store.py / retriever.py / formation.py / types.py) |
| 前端状态管理 | `frontend/src/store/appStore.tsx` → `frontend/src/types/index.ts` |
| WebSocket | `api/websocket/handlers.py` → `frontend/src/hooks/useWebSocket.ts` |
| LLM 客户端 | `core/llm/` (base.py / factory.py / openai_client.py / anthropic_client.py) |

---

## 6. 测试命令速查

```bash
# 全部测试
python3 -m pytest backend/tests/ -q

# 单元测试 (详细)
python3 -m pytest backend/tests/unit/ -v

# 集成测试
python3 -m pytest backend/tests/integration/ -v

# 指定模块
python3 -m pytest backend/tests/unit/test_bus.py -v
python3 -m pytest backend/tests/unit/test_memory.py -v
python3 -m pytest backend/tests/unit/test_capability.py -v

# 带输出
python3 -m pytest backend/tests/ -v --tb=short -s

# 前端构建检查
cd frontend && npx tsc --noEmit && npx vite build
```

---

## 7. 环境配置速查

### 后端启动

```bash
cd backend/src
python -m api.main                    # 直接运行
uvicorn api.main:app --port 8001 --reload  # 热重载
```

### 前端启动

```bash
cd frontend
npm install
npm run dev                           # 开发模式
npm run build && npm run preview      # 生产构建
```

### 环境变量

```bash
export LLM_PROVIDER=openai            # openai / anthropic
export LLM_API_KEY=sk-your-key
export LLM_MODEL=gpt-4
export LLM_BASE_URL=                  # 自定义端点 (可选)
export MEMORY_BACKEND=memory          # memory / chroma
```

### 重要端口

| 端口 | 服务 |
|------|------|
| 8001 | 后端 FastAPI |
| 3000 | 前端 Vite Dev Server |

### 重要路径

| 路径 | 说明 |
|------|------|
| `backend/src/config.yaml` | LLM 运行时配置 (API Key) |
| `config/*.yaml` | 组件配置 (Agent/Pipeline/Capability/System) |
| `backend/src/api/main.py` | 应用入口 + 初始化流程 |
| `backend/src/core/config.py` | 配置加载逻辑 |

---

## 8. 项目统计

| 指标 | 数值 |
|------|------|
| Python 源文件 | 82 |
| 前端 TS/TSX | 16 |
| 前端 CSS | 11 |
| 后端代码行数 | ~8,300 |
| 前端代码行数 | ~5,100 |
| 测试代码行数 | ~4,900 |
| 测试用例 | 550 |
| REST API | 31 端点 |
| WebSocket | 1 端点 |
| 前端面板 | 9 个 |
| YAML 配置 | 6 个文件 |

---

_此文档与 CLAUDE.md、README.md 保持一致。如有架构变动，请同步更新。_
