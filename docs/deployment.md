# 部署指南

> 最后更新: 2026-03-25

## 开发环境搭建

### 前置要求

- Python 3.10+
- Node.js 18+
- npm
- Git

### 1. 克隆项目

```bash
git clone <repo-url>
cd agentic-system
```

### 2. 后端安装

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置 LLM

复制配置模板:

```bash
cp config.example.yaml src/config.yaml
```

编辑 `src/config.yaml`:

```yaml
llm:
  provider: openai          # openai 或 anthropic
  model: gpt-4              # 模型名称
  api_key: sk-your-key      # API Key
  base_url: ""              # 自定义端点 (可选)

memory:
  backend: "memory"         # "memory" (内存) 或 "chroma" (ChromaDB 持久化)
```

或使用环境变量:

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-your-key
export LLM_MODEL=gpt-4
# export LLM_BASE_URL=https://custom-api.example.com  # 可选
```

### 4. 启动后端

```bash
cd backend/src

# 方式 1: 直接运行
python -m api.main

# 方式 2: uvicorn (支持热重载)
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
```

后端在 http://localhost:8001 启动。

### 5. 前端安装与启动

```bash
cd frontend
npm install
npm run dev
```

前端在 http://localhost:3000 启动。

### 6. 验证

- 访问 http://localhost:8001/api/health 检查后端状态
- 访问 http://localhost:8001/docs 查看 Swagger API 文档
- 访问 http://localhost:3000 使用前端界面

---

## 生产构建

### 前端构建

```bash
cd frontend
npm run build    # 输出到 dist/
npm run preview  # 预览生产构建
```

### 后端生产运行

```bash
cd backend/src
uvicorn api.main:app --host 0.0.0.0 --port 8001 --workers 1
```

> **注意**: 由于使用内存存储和 asyncio 事件循环，目前仅支持单 worker 模式。

---

## 配置说明

### 配置文件结构

| 文件 | 路径 | 用途 |
|------|------|------|
| `config.yaml` | `backend/src/` | LLM API Key、模型等运行时配置 |
| `agents.yaml` | `config/` | 智能体定义 |
| `triggers.yaml` | `config/` | 事件扳机规则 |
| `workflows.yaml` | `config/` | 工作流模板 |
| `capabilities.yaml` | `config/` | 能力插件定义 |
| `system.yaml` | `config/` | 全局系统配置 |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | openai |
| `LLM_API_KEY` | API Key | (空) |
| `LLM_MODEL` | 模型名称 | gpt-3.5-turbo |
| `LLM_BASE_URL` | 自定义 API 端点 | (空) |
| `MEMORY_BACKEND` | 记忆后端 | memory |
| `MEMORY_PERSIST_DIR` | ChromaDB 持久化目录 | ./data/chroma |
| `BUS_QUEUE_SIZE` | 消息队列大小 | 1000 |
| `BUS_HISTORY_SIZE` | 消息历史保留数 | 500 |

### CORS 配置

默认允许的前端源 (在 `main.py` 中配置):
- `http://localhost:3000`
- `http://localhost:3001`

如需修改，编辑 `backend/src/api/main.py` 中的 `allow_origins` 列表。

---

## 运行测试

```bash
# 全部测试
python3 -m pytest backend/tests/ -q

# 带详细输出
python3 -m pytest backend/tests/ -v --tb=short

# 仅单元测试
python3 -m pytest backend/tests/unit/ -v

# 仅集成测试
python3 -m pytest backend/tests/integration/ -v
```

---

## 常见问题

### 后端启动失败: ModuleNotFoundError

确保从 `backend/src` 目录启动:

```bash
cd backend/src
python -m api.main
```

### 前端连接不上后端

1. 确认后端在 8001 端口运行: `curl http://localhost:8001/api/health`
2. 检查 CORS 配置是否包含前端地址
3. 检查浏览器控制台错误信息

### ChromaDB 相关错误

ChromaDB 是可选依赖。如果不需要向量检索:

```yaml
# config.yaml
memory:
  backend: "memory"  # 使用内存后端
```

如果需要 ChromaDB:

```bash
pip install chromadb
```

### API Key 问题

- 确保 API Key 有效且有足够额度
- 使用环境变量 `LLM_API_KEY` 设置 Key，避免在配置文件中明文存储
- 也可以在前端 Settings 面板中动态配置
