# 部署指南

> 最后更新: 2026-06-02
> 当前部署口径已按 Agent Run、Project 工作区、能力库、MCP 模板和全局访问密码同步。

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
  backend: "chroma"         # 默认 ChromaDB 持久化；开发测试可改 "memory"
  persist_dir: "./data/chroma"
  reflection_min_turns: 3   # 默认累计后反思；显著偏好/待办/项目决策可提前触发
  reflection_max_messages: 12
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
uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
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
uvicorn api.main:app --host 127.0.0.1 --port 8001 --workers 1
```

> **注意**: 由于使用内存存储和 asyncio 事件循环，目前仅支持单 worker 模式。

---

## 配置说明

### 配置文件结构

| 文件 | 路径 | 用途 |
|------|------|------|
| `config.yaml` | `backend/src/` | LLM API Key、模型等运行时配置 |
| `agents.yaml` | `config/` | 智能体定义 |
| `capabilities.yaml` | `config/` | 能力插件定义 |
| `mcp_servers.yaml` | `config/` | MCP 模板库，默认禁用，按 Agent 装配 |
| `system.yaml` | `config/` | 全局系统配置 |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | openai |
| `LLM_API_KEY` | API Key | (空) |
| `LLM_MODEL` | 模型名称 | gpt-3.5-turbo |
| `LLM_BASE_URL` | 自定义 API 端点 | (空) |
| `MEMORY_BACKEND` | 记忆后端 | chroma |
| `MEMORY_PERSIST_DIR` | ChromaDB 持久化目录 | ./data/chroma |
| `MEMORY_FALLBACK_TO_MEMORY_ON_ERROR` | Chroma 初始化失败时降级内存 | true |
| `AGENTIC_WORKSPACE_ROOT` | 文件工具、Artifact、transcript 的统一工作区根 | ./workspace |
| `ENABLE_SHELL_TOOL` | 是否启用 bash 工具 | false |
| `BUS_QUEUE_SIZE` | 消息队列大小 | 1000 |
| `BUS_HISTORY_SIZE` | 消息历史保留数 | 500 |

运行态目录说明：

- `workspace/projects/`：导入的 Project 工作区。
- `workspace/runs/`：未显式绑定工作区的 Agent Run 临时目录。
- `workspace/sessions/`：聊天会话自动工作区。
- `workspace/tasks/`：transcript JSONL。
- `workspace/artifacts/`：前端可预览/下载的 Artifact。
- `data/`：人格、记忆和运行时本地数据。

这些目录通常不入库，也不应提交密钥或用户上传资料。

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

ChromaDB 是默认持久化记忆依赖。正常部署请安装:

```bash
pip install chromadb
```

如果只是临时开发、且不需要持久化记忆:

```yaml
# config.yaml
memory:
  backend: "memory"  # 使用内存后端
```

### API Key 问题

- 确保 API Key 有效且有足够额度
- 使用环境变量 `LLM_API_KEY` 设置 Key，避免在配置文件中明文存储
- 也可以在前端 Settings 面板中动态配置

---

## A11 公网部署密码门禁

> 适用场景：把后端 + 前端暴露在公网（VPS / 反代）时，需要在服务前再加一层访问密码，
> 避免任何人都能调你的 LLM API、读你的记忆库或动态创建 Agent。

### 启用方式

在 `config/system.yaml` 设置 `server.access_password`：

```yaml
server:
  access_password: "<your-secret>"      # 空字符串 = 不开启门禁（开发态）
  failed_login_lockout_seconds: 60      # 失败计数滑动窗口
  failed_login_max_attempts: 5          # 同 IP 在窗口内累计 5 次错误后被锁定
```

行为：

- HTTP 端：所有 `/api/*` 请求需带 `Authorization: Bearer <password>`。`/api/health`、
  `/docs`、`/openapi.json`、`/redoc` 永远豁免。
- WebSocket：连接时需带 `?token=<password>`。token 缺失或错误 → 服务端
  `close(code=4401, reason="auth_invalid")`，前端会自动跳回登录页。
- 同一 IP 在 `failed_login_lockout_seconds` 滑动窗口内累计 ≥
  `failed_login_max_attempts` 次失败后，即使带正确 token 也会被直接 429 `rate_limited`，
  失败时间戳过期后自动恢复。
- 修改 `system.yaml` 后需重启后端，或调用 `clear_system_config_cache()` 让中间件重新读配置。

### 前端体验

- 首次访问会弹登录页（`frontend/src/components/LoginPage.tsx`），输入正确密码后
  写入 `localStorage.agentic.auth_token`，主面板才会渲染。
- 任意 API 返回 401 时，`api/client.ts` 拦截器会自动清空 token + 派发
  `agentic:auth-failed` 事件，App 监听后退回登录页。
- WebSocket 重连时也会读最新 token，重启反代或修改密码后用户只需重新登录。

### nginx 反向代理示例（含日志屏蔽）

> ⚠️ **风险点 R4**：WebSocket 走 query string `?token=`，默认 access_log 会把 token 明文记录到磁盘。
> 公网部署务必配 HTTPS + 日志屏蔽，避免日志泄露撞库。

```nginx
# /etc/nginx/conf.d/agentic.conf

# 把 ?token=xxx 替换成 (masked) 写入 access_log
map $request $request_masked {
    default $request;
    ~*^(.*)token=[^&\s]+(.*)$ "$1token=(masked)$2";
}

log_format masked '$remote_addr - $remote_user [$time_local] '
                  '"$request_masked" $status $body_bytes_sent '
                  '"$http_referer" "$http_user_agent"';

upstream agentic_backend {
    server 127.0.0.1:8001;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain/privkey.pem;

    access_log /var/log/nginx/agentic.access.log masked;
    error_log  /var/log/nginx/agentic.error.log warn;

    # 前端静态资源
    root /var/www/agentic/frontend/dist;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }

    # REST API
    location /api/ {
        proxy_pass http://agentic_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # WebSocket（含 token query 参数，access_log 已经屏蔽）
    location /ws {
        proxy_pass http://agentic_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400s;       # 长连接
    }
}

# HTTP 强制跳 HTTPS
server {
    listen 80;
    server_name your-domain.example.com;
    return 301 https://$server_name$request_uri;
}
```

### 安全建议

- **务必走 HTTPS**：HTTP 下密码会在 Authorization header 与 `?token=` 中明文传输。
- **关掉 OpenAPI 暴露**：生产环境可以在 FastAPI 启动时加 `docs_url=None, redoc_url=None`
  避免攻击者扫描 API 形态。
- **`access_password` 用高熵字符串**：建议 ≥ 24 字符随机串，配合 `failed_login_max_attempts`
  让暴力破解成本极高。
- **注意泄漏面**：浏览器历史记录、`access_log`、`error_log` 都可能记 query string。
  反代的 access_log 必须按上面 `map` 屏蔽 token；前端不要把 token 拼到 `<a href="/ws?token=...">`
  之类的可见 DOM 里。
- **不要复用密码**：这只是“一道门”，不是身份系统。多用户场景请加正经鉴权（OIDC / Session）。
