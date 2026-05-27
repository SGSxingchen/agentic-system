# 自由化与 UI 增强设计 — 2026-05-28

> 拆掉过度防御 + 公网暴露密码 + UI 小功能。
>
> 设计哲学：默认放开，想锁的人自己加规则。

**版本**: v1.0
**日期**: 2026-05-28
**作者**: 项目维护者
**状态**: 设计阶段，未实施

---

## 0. 摘要

本 spec 覆盖 7 项改动，分两条主轴：

**主轴一 — 把过度防御的"审批闸门"改成"审计日志"：**

- A4 — 拆掉 `evolution_config.py:HIGH_RISK_TOOLS` 对 `agent_creator` 的硬限制；让 agent_creator 主动给被创建 Agent 配齐工具栈
- A8 — 把 `POST /api/evolution/reload` 暴露成 `AgentPanel` 顶部一个按钮，造完 Agent / 改完工具不用切终端
- A10 — 砍掉 `agent_management.py` 三段式 propose-approve-apply、`persona_evolution.py` / `persona_management.py` 的 `admin_approved` 闸门、`dispatch_agent.py:max_depth=1`、management 工具只许挂 agent_manager 的限制；统一换成"调用即生效 + 写日志"

**主轴二 — 部署友好 + UI 体感：**

- A11 — `system.yaml: server.access_password` 单密码全局门禁，HTTP/WS 都要过；公网暴露的最低限度防爆破
- B1 — 全类型附件上传与下发（图片走 vision、文本/PDF 通过工作区路径让 Agent 自己读、ZIP 等大文件留路径）
- B4 — Agent 名后挂 model 徽标（数据已暴露，纯前端展示）
- B5 — `ChatroomPanel` 设置抽屉的英文 key 改中文 label + 副说明（含为 A1 / A21 预留的两项）

整体不引入新框架；中间件、附件存储、前端 token 拦截都是 FastAPI / fetch / Vite 既有能力。

---

## 1. 设计哲学：审批换审计

当前代码里散布着这种结构：

```python
def _admin_decision(kwargs, *, action):
    if not kwargs.get("admin_approved"):
        return {"decision": "deny", "reason": ...}
    if not str(kwargs.get("reviewer") or "").strip():
        return {"decision": "deny", "reason": ...}
    expected = os.getenv("PERSONA_ADMIN_TOKEN", "").strip()
    if expected and str(kwargs.get("admin_token") or "") != expected:
        return {"decision": "deny", "reason": ...}
    return {"decision": "allow"}
```

— 见 `agent_management.py:124-136`、`persona_evolution.py:17-31`、`persona_management.py:19-33`。

这套是「单机本地 Agent 系统」复刻多人审计部署的产物，与现实使用脱节：

1. **唯一的"审核人"就是 Agent 自己**。为了通过校验，Agent 会硬编码 `admin_approved=true, reviewer="self"`，闸门变形式主义。
2. **被锁住的是合法的能力**：`agent_creator` 不能给新 Agent 挂 `bash`/`write_file`/`dispatch_agent`，导致工具栈先天残废，要么不可用要么得用户手动改 yaml 再重启。
3. **真正应对误操作的兜底是 git + 备份，不是布尔字段**。Agent 多打了一次工具远比 git revert 一次更日常。

新方针：

- **写操作直接生效**。删除所有 `admin_approved` / `reviewer` / `admin_token` 必填校验。
- **每次写都留审计**：写文件前后做一次 `structlog.info("config_change", agent=..., diff=..., caller_task_id=..., timestamp=...)`；transcript 已经在跟，不用单独搞日志后端。
- **想锁的部署在 `system.yaml` 加规则**：`agent_creation.forbidden_tools`、`dispatch.max_depth` 这些 escape hatch 给真正在意安全的部署。
- **回溯靠 git**：所有 yaml 改动都通过 `save_yaml_config` 落盘；建议在 Phase 2 加上 `subprocess.run(["git", "commit", "-m", f"agent_config: {agent_name}"])`，把 author 标成调用方 task id，便于回溯。本 spec 不强制要求自动 commit，先把审批闸门拆掉是优先级。

下面 7 节按"先快后重"排序。

---

## 2. A4 — `HIGH_RISK_TOOLS` 默认放开 + agent_creator LM 自决

### 2.1 现状定位

| 文件:行 | 防御代码 | 影响 |
|---|---|---|
| `backend/src/capabilities/tools/evolution_config.py:27-33` | `HIGH_RISK_TOOLS = {bash, write_file, create_agent_config, create_dynamic_tool_config, dispatch_agent}` | 硬编码集合 |
| `evolution_config.py:331-339` | `if high_risk_tools: return {"error": "create_agent_config cannot grant high-risk tools..."}` | 创建路径直接拒绝 |
| `agent_management.py:40-46` | 同样的 `HIGH_RISK_TOOLS` 集合 | 第二份硬编码 |
| `agent_management.py:227-238` | `_validate_patch` 里 `if high_risk and not allow_high_risk_tools: errors.append(...)` | patch 路径默认拒绝 |
| `agent_management.py:323-330` | `if management_tools: return {"error": "Agent management tools can only be mounted on agent_manager..."}` | management 工具只许挂 agent_manager |

### 2.2 改动方案

**A. 删除 `HIGH_RISK_TOOLS` 默认拒绝**

`evolution_config.py`：

- 移除 `HIGH_RISK_TOOLS` 常量及第 331-339 行的拒绝分支。
- 在写入前打印 `print(f"[INFO] agent_creator: created '{name}' with tools={tools}")`，结构化日志由 `core/utils/logger.py` 注入即可。

`agent_management.py`：

- 移除 `HIGH_RISK_TOOLS` 常量。
- `_validate_patch` 删除 `allow_high_risk_tools` 参数与第 232-238 行；保留对 `tools` 类型的校验（仍要求是非空字符串列表）。
- 把所有 `update_*` 工具的 schema 里相关的 `allow_high_risk_tools` 字段直接删掉。

**B. `system.yaml` escape hatch（默认空）**

```yaml
# config/system.yaml — 新增段
agent_creation:
  forbidden_tools: []   # 全局禁止的 tool 名单。默认空，开放一切。
                        # 想锁的部署可填，例如: ["bash"] 拒绝任何 Agent 挂 bash。
```

加载逻辑放在 `core/config.py` 的 `SystemConfig` 里：

```python
class AgentCreationConfig(BaseModel):
    forbidden_tools: List[str] = Field(default_factory=list)
```

校验点改成：

```python
forbidden = set(config.get("agent_creation", {}).get("forbidden_tools") or [])
violation = sorted(set(tools) & forbidden)
if violation:
    return {"error": f"tools forbidden by system.yaml: {violation}"}
```

**C. agent_creator prompt 调整**

`config/agents.yaml` 里 `agent_creator.system_prompt` 改成主动放开，要点：

> 你创建的新 Agent **必须**根据职责挂齐工具栈，包括但不限于 `bash` / `write_file` / `read_file` / `dispatch_agent` / `web_fetch` / `WebSearch`。任何"非纯规划型"Agent 都应该能动手——不要为了"安全"创建残废 Agent。
>
> 工具栈最小集示例：
> - 编码类（如 frontend_dev、backend_dev）：`read_file` `write_file` `bash` `dispatch_agent` `web_fetch`
> - 调研类（如 doc_writer）：`web_fetch` `WebSearch` `read_file` `write_file`
> - 规划类（如 architect）：`dispatch_agent` 加只读工具
>
> 装载 Skill / 拉取仓库等资源不需要新工具：`WebSearch` 找位置、`web_fetch` 抓 README、`bash` 跑 `git clone`、`write_file` 落盘配置即可。

同时移除老 prompt 里"只创建低风险 Agent"那段（`config/agents.yaml:99`）。

### 2.3 兼容与回退

- `evolution_config.py` 仍保留 `PROTECTED_AGENT_NAMES`（assistant、planner、coder 等）防覆盖原生 Agent。
- 所有写操作仍走原有 `save_yaml_config`，文件级别可以 git diff 回溯。
- 若部署需要恢复旧防御，只需在 `agent_creation.forbidden_tools` 填回 5 个工具名即可。

---

## 3. A8 — `AgentPanel` 顶部"重新装载"按钮

### 3.1 现状

`POST /api/evolution/reload` 已经存在（`backend/src/api/routes/evolution.py:720-735`），调用 `reload_agent_fn()` 触发 `main.py:reload_agents()`，会清空 capability registry 里的 AgentCapability + 重新读 `config/agents.yaml`。

但 `frontend/src/components/AgentPanel.tsx` 没暴露入口，agent_creator / tool_creator 写完 yaml 之后只能：

1. 给用户发"请重启后端"消息（见 agents.yaml 里的 prompt）
2. 或者用户去命令行 `curl -X POST .../api/evolution/reload`

### 3.2 改动方案

**前端**：`AgentPanel.tsx` 顶部 toolbar 加按钮：

```tsx
const [reloading, setReloading] = useState(false)
const [lastReload, setLastReload] = useState<Date | null>(null)
const [reloadError, setReloadError] = useState<string | null>(null)

const handleReload = async () => {
  setReloading(true)
  setReloadError(null)
  const res = await fetch('/api/evolution/reload', { method: 'POST' })
  setReloading(false)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    setReloadError(`HTTP ${res.status}: ${text || res.statusText}`)
    return
  }
  setLastReload(new Date())
  // 触发 AgentPanel 重新拉 listAgents()
  await refreshAgents()
}
```

**UI**：

- 按钮文案：「重新装载 Agent」
- 旁边小字：`上次装载: 14:32:05` 或 `从未装载`
- 装载中：按钮 disabled + 自旋图标 + 文案改「装载中…」
- 失败：红色提示条显示 `reloadError`，**不要静默失败**（这是 spec 显式要求）
- 成功：3 秒消失的 toast「已装载 N 个 Agent」（N 从 `health.agents` 里取）

**API 客户端**：在 `frontend/src/api/client.ts` 新增：

```ts
export async function reloadEvolutionExtensions(): Promise<APIResponse<unknown>> {
  return post('/api/evolution/reload')
}
```

### 3.3 边界

- 装载本身只是热重载，**不会丢消息历史/任务进度**（因为 task registry / chat session store / chatroom store 都是单独的进程级单例）。
- 装载会重新解析 `agents.yaml`，**当前正在跑的 Agent Run / chatroom speaking task 不受影响**（它们已持有 capability 实例引用），只影响下一次 dispatch。
- 同时多人按按钮：后端 `reload_agents()` 没加锁，多次连续装载理论上会触发并发的 unregister/register，但因为单 worker FastAPI 异步串行，不会并发。

---

## 4. A10 — 全面拆三段式审批 / max_depth / management 限制

### 4.1 现状（5 处）

**4.1.1 Agent 配置三段式**

`agent_management.py` 实现了 4 个工具：`read_agent_config` / `validate_agent_config_patch` / `propose_agent_config_patch` / `apply_agent_config_patch`。

- `propose_agent_config_patch`（行 481-550）：返回 `requires_admin_approval: True` + `apply_requirements: {admin_approved, reviewer}`，自身不写入。
- `apply_agent_config_patch`（行 553-650）：`check_permissions` 走 `_admin_decision`（行 124-136），要求 `admin_approved=true` + `reviewer` + 可选 `admin_token`。

**4.1.2 Persona 三段式**

- `persona_evolution.py:131-184` `generate_persona_patch_proposal` 返回 pending proposal
- `persona_evolution.py:187-237` `apply_confirmed_persona_patch` 走 `_admin_decision`（行 17-31）
- `persona_management.py:36-247` 内 `manage_persona_definition` / `manage_persona_binding` 的写操作分支同样必经 `_admin_decision`

**4.1.3 dispatch_agent 嵌套**

`dispatch_agent.py:46` `_MAX_DEPTH = 1`。
`check_permissions`（行 93-103）+ `execute` 的二次校验（行 117-124）：子 Agent 内部再调 `dispatch_agent` 直接返错。

**4.1.4 management 工具只挂 agent_manager**

`agent_management.py:296-306` `_validate_agent_specific_patch`：

```python
if agent_name != "agent_manager" and management_tools:
    errors.append("Agent 管理工具只能挂载到 agent_manager: ...")
```

`evolution_config.py:323-330` `create_agent_config` 直接拒绝。

### 4.2 改动方案

**4.2.1 Agent 配置：合并成单一动词**

废弃 `propose_agent_config_patch` + `apply_agent_config_patch`，新增单一工具 `update_agent_config`：

```python
class UpdateAgentConfigCapability(CapabilityBase):
    name = "update_agent_config"
    # parameters: agent_name (required), patch (required), reason (optional)
    async def execute(self, **kwargs):
        agent_name = kwargs["agent_name"]
        patch, errors = _validate_patch(kwargs.get("patch"))  # 删 allow_high_risk_tools
        if errors: return {"success": False, "errors": errors}
        data = _load_agents_yaml()
        prev = deepcopy(data)
        agent = _find_agent(data, agent_name)
        if not agent: return {"error": f"agent '{agent_name}' not found"}
        updated = _apply_patch_to_agent(agent, patch)
        # 保留：reload_or_rollback 仍要做（reload 失败回滚是数据完整性，不是审批）
        try:
            await _reload_or_rollback(data, prev)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc), "rolled_back": True}
        # 审计日志（替代审批）
        logger.info(
            "agent_config_updated",
            agent_name=agent_name,
            changed_fields=sorted(patch.keys()),
            reason=kwargs.get("reason", ""),
            caller_task_id=get_parent_task_id(),
        )
        return {"success": True, "agent": _sanitize_agent_config(updated), "changed_fields": [...]}
```

`read_agent_config` + `validate_agent_config_patch` 保留（这俩本来就是只读，没碍事）。

**4.2.2 Persona：同样收敛**

废弃 `generate_persona_patch_proposal` + `apply_confirmed_persona_patch`。新增 `update_persona`：

- 直接传 `persona_id` + `patch`，调用 `PersonaStore().update_persona(persona_id, patch)`。
- 历史版本机制保留——`PersonaStore` 内部已经有 `versions` 表，每次 update 自动写一个 version，可以前端展示「版本历史」按钮回滚。
- `persona_management.py` 里 `manage_persona_definition` / `manage_persona_binding` 删除 `_admin_decision`，所有 mutate 操作直接走 `service.bind_agent(...)` 等。

注意：proposal 流程**不是删干净**——`PersonaStore.list_proposals()` 当前持有的存量 pending proposals 仍然要能列出和处理；但**不再有任何工具会创建新的 pending proposal**。前端 `PersonaPanel` 的 proposals 区改成"历史/归档"语义。

**4.2.3 dispatch_agent：放宽到默认 5**

`dispatch_agent.py:46`：

```python
_DEFAULT_MAX_DEPTH = 5  # 原 1

def _resolve_max_depth() -> int:
    cfg = load_config().get("dispatch", {})
    return int(cfg.get("max_depth", _DEFAULT_MAX_DEPTH))
```

`check_permissions` + `execute` 用 `_resolve_max_depth()`。

`system.yaml` 新增：

```yaml
dispatch:
  max_depth: 5   # dispatch_agent 嵌套上限。默认 5，0=不允许嵌套，-1=无限。
```

**4.2.4 management 工具放开**

直接删除 `agent_management.py:296-306` 的 `_validate_agent_specific_patch`（整个函数）和它在三处的调用（`validate_agent_config_patch.execute` / `propose_*` / `apply_*`）。

也删除 `evolution_config.py:323-330` 的拒绝分支。

任何 Agent 都可以挂 `read_agent_config` / `update_agent_config`。Agent 自己读自己的配置、给自己加工具完全合法——这就是 self-evolving Agent 该有的样子。

### 4.3 关键边界：审批换审计 ≠ 删掉一切安全

**仍保留**：

| 保留项 | 文件 | 理由 |
|---|---|---|
| `_validate_patch` 字段白名单（`ALLOWED_AGENT_FIELDS`） | `agent_management.py:28-39` | 防止注入未知字段（如 `__import__`） |
| `_validate_skill_paths` 路径越权检查 | `agent_management.py:171-201` | 阻止跳出 project root |
| `_validate_default_workspace_root` | `agent_management.py:156-168` | 阻止跳出 ./workspace |
| `MASKED_API_KEY_VALUES` 脱敏 | `agent_management.py:54` | 不把 api_key 通过 LLM 输出泄露 |
| `_reload_or_rollback` 失败回滚 | `agent_management.py:346-366` | 数据完整性 |
| `PROTECTED_AGENT_NAMES` 防覆盖 | `evolution_config.py:17-26` | 防止 agent_creator 把 assistant 改坏 |
| Persona `versions` 历史 + rollback | `core/persona.py` | 不删人格历史，可回滚 |

**审计日志**：所有 `update_agent_config` / `update_persona` / `bind_agent` 调用都写 `structlog.info` 一行，字段包括 `caller_task_id`、`agent_name`、`changed_fields`、`timestamp`。这些日志就是 git diff 之外的第二张证据网。

**Phase 2 候选**（不在本次实施范围）：在 `_reload_or_rollback` 成功后追加 `git add config/agents.yaml && git commit -m "agent_update: {agent_name} by task {task_id}"`，把 task_id 直接写进 git author/log。这是把"审计"做满的下一步，本 spec 不强制要求。

---

## 5. A11 — 全局访问密码

### 5.1 现状

后端无任何认证。`CORS` 只配了 `allow_origins`，公网部署等于裸奔。

### 5.2 改动方案

**5.2.1 配置入口**

`config/system.yaml`：

```yaml
server:
  host: "127.0.0.1"
  port: 8001
  cors_origins: ["http://localhost:3000", "http://localhost:3001"]
  access_password: ""   # 空 = 不开启密码门禁（默认）。非空字符串 = 启用。
                         # 建议至少 12 位、含大小写+数字。
```

`SystemConfig.ServerConfig`（在 `core/config.py` 加）：

```python
class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8001
    cors_origins: List[str] = Field(default_factory=list)
    access_password: str = ""
```

**5.2.2 后端中间件**

`backend/src/api/main.py` 在 `add_middleware(CORSMiddleware, ...)` 之后追加：

```python
from .middleware.access_password import AccessPasswordMiddleware
app.add_middleware(AccessPasswordMiddleware, password=SERVER_CONFIG.get("access_password", ""))
```

新文件 `backend/src/api/middleware/access_password.py`：

```python
from collections import defaultdict
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

OPEN_PATHS = {"/api/health"}            # 健康检查不要门
OPEN_PREFIXES = ("/static/",)            # 前端静态资源（如果同源部署）
LOCK_DURATION = 60                       # 秒
MAX_FAILS = 5

class AccessPasswordMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, password: str):
        super().__init__(app)
        self.password = (password or "").strip()
        self._fails: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request, call_next):
        if not self.password:
            return await call_next(request)

        path = request.url.path
        if path in OPEN_PATHS or any(path.startswith(p) for p in OPEN_PREFIXES):
            return await call_next(request)

        # WebSocket 走 ?token=xxx (FastAPI 的 WS 不会走 BaseHTTPMiddleware，
        # 因此 WS 鉴权要在 /ws 处理函数里做，见 5.2.4)
        if path.startswith("/ws"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        if self._is_locked(client):
            return JSONResponse(
                {"status": "error", "error": "auth_locked",
                 "message": "too many failed attempts; try again in 60s"},
                status_code=429,
            )

        token = request.headers.get("authorization", "")
        if not token.startswith("Bearer "):
            return JSONResponse({"status": "error", "error": "auth_required"}, status_code=401)
        provided = token[7:].strip()

        # 用 hmac.compare_digest 防时序攻击
        import hmac
        if not hmac.compare_digest(provided, self.password):
            self._record_fail(client)
            return JSONResponse({"status": "error", "error": "auth_invalid"}, status_code=401)

        return await call_next(request)

    def _is_locked(self, client: str) -> bool:
        now = time.time()
        recent = [t for t in self._fails[client] if now - t < LOCK_DURATION]
        self._fails[client] = recent
        return len(recent) >= MAX_FAILS

    def _record_fail(self, client: str) -> None:
        self._fails[client].append(time.time())
```

**5.2.3 错误响应**

| 场景 | HTTP | body |
|---|---|---|
| 未带 header | 401 | `{"status": "error", "error": "auth_required"}` |
| 密码错 | 401 | `{"status": "error", "error": "auth_invalid"}` |
| 锁定 | 429 | `{"status": "error", "error": "auth_locked", "message": ...}` |

前端通过 `error` 字段精确判断（`auth_required` → 跳登录页；`auth_invalid` → 提示密码错；`auth_locked` → 提示稍后再试）。

**5.2.4 WS 鉴权**

`websocket_route` 在 `await ws_handler(websocket)` 前先校验：

```python
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    pwd = SERVER_CONFIG.get("access_password", "")
    if pwd:
        token = websocket.query_params.get("token", "")
        import hmac
        if not hmac.compare_digest(token, pwd):
            await websocket.close(code=4401, reason="auth_invalid")
            return
    await ws_handler(websocket)
```

WS 握手没有标准 401，用 `4401` 这个自定义关闭码（>4000 范围）传递鉴权失败，前端识别后跳登录页。

**5.2.5 前端**

新增 `frontend/src/api/auth.ts`：

```ts
const TOKEN_KEY = 'agentic_access_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)
```

`frontend/src/api/client.ts:fetchAPI` 改造：

```ts
async function fetchAPI<T>(path, options) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options?.headers,
  }
  const res = await fetch(`${API_BASE}${path}`, { headers, ...options })
  if (res.status === 401) {
    const body = await res.json().catch(() => ({}))
    clearToken()
    window.dispatchEvent(new CustomEvent('agentic:auth-required',
      { detail: { error: body.error || 'auth_required' } }))
    return { status: 'error', message: body.error || 'auth_required' }
  }
  // ...
}
```

`frontend/src/hooks/useWebSocket.ts:connect` 改造：

```ts
const fullUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url
const ws = new WebSocket(fullUrl)
ws.onclose = (ev) => {
  // ev.code === 4401 → auth_invalid
  if (ev.code === 4401) {
    clearToken()
    window.dispatchEvent(new CustomEvent('agentic:auth-required'))
    return  // 不自动重连
  }
  // ... 既有重连逻辑
}
```

新增 `frontend/src/components/LoginGate.tsx`：

```tsx
function LoginGate({ children }) {
  const [authed, setAuthed] = useState<boolean | null>(null)
  // 启动时探测：调一次 /api/health（开放） + /api/agents（被门挡）
  useEffect(() => {
    fetch('/api/agents', { headers: { Authorization: `Bearer ${getToken()}` } })
      .then(res => setAuthed(res.status !== 401))
  }, [])
  useEffect(() => {
    const handler = () => setAuthed(false)
    window.addEventListener('agentic:auth-required', handler)
    return () => window.removeEventListener('agentic:auth-required', handler)
  }, [])
  if (authed === null) return <div>加载中…</div>
  if (!authed) return <PasswordPrompt onSuccess={() => setAuthed(true)} />
  return <>{children}</>
}
```

`App.tsx` 顶层包一层：`<AppProvider><LoginGate><AppContent /></LoginGate></AppProvider>`。

`PasswordPrompt`：单 input + 提交按钮 + 错误提示。提交后用一次 `fetch('/api/agents', { headers: Authorization })` 验证密码，成功就 `setToken(input); onSuccess()`。

**5.2.6 显式不做**

- **不实现账号系统**（用户明确拒绝）
- 不做密码哈希存储——`system.yaml` 里就是明文，权衡是部署简单 vs 多人共享密钥风险；本系统只面向单人/小团队公网暴露
- 不做 token 过期 / 续签——单密码全局，一次输入永久（直到 logout 或换密码）
- 不做 CSRF token——纯 JSON API + 没有 cookie 鉴权，CSRF 不适用

---

## 6. B1 — 附件支持

### 6.1 设计目标

ChatPanel 与 ChatroomPanel 都能上传任意类型文件，让 Agent 看图（vision）、读文档（read_file）、处理压缩包（路径传递）。

### 6.2 数据模型

`backend/src/core/attachment.py`（新文件）：

```python
@dataclass
class Attachment:
    id: str                    # uuid4
    filename: str              # 原文件名（已 sanitize）
    mime_type: str             # 由后端 magic 探测，不信前端
    size_bytes: int
    storage_path: str          # 绝对路径，落在 data/attachments/<scope_hash>/<id>__<safe>
    created_at: datetime
    uploaded_by: str           # "user" 或 "agent:<name>"
    scope: str                 # "chat_session:<id>" 或 "chatroom:<id>"
    meta: dict                 # 扩展位
```

**JSON 持久化**：`data/attachments/_index.json`（全局清单）+ 单文件落盘。

**目录结构**：

```
data/attachments/
├── _index.json
├── chatroom_<hash8>/                # scope_hash = sha256(scope)[:8]
│   └── <attachment_id>__<safe_filename>
└── chat_session_<hash8>/
    └── <attachment_id>__<safe_filename>
```

**安全文件名**：`safe_filename = re.sub(r'[^\w.\-]', '_', filename)[:120]`。

### 6.3 配置

`system.yaml`：

```yaml
attachments:
  enabled: true
  storage_dir: "./data/attachments"
  max_size_mb: 50                    # 单文件上限
  allowed_mime_prefixes:             # 白名单前缀
    - "image/"                       # png/jpg/webp/gif → 走 vision
    - "text/"
    - "application/pdf"
    - "application/json"
    - "application/zip"
    - "application/x-tar"
    - "application/gzip"
  per_scope_quota_mb: 500            # 单 scope 累计上限，超过就拒新上传
```

### 6.4 后端 API

新路由 `backend/src/api/routes/attachments.py`：

| 方法 | 路径 | 入参 | 返回 |
|---|---|---|---|
| POST | `/api/attachments` | multipart `file` + form `scope` + `uploaded_by` | `Attachment` |
| GET | `/api/attachments/{id}` | — | 二进制流 + 正确 Content-Type |
| GET | `/api/attachments` | query `?scope=...` | `Attachment[]` |
| DELETE | `/api/attachments/{id}` | — | `{success: true}` |

**关键校验顺序**：

1. 大小 ≤ `max_size_mb`
2. `python-magic` 探 MIME（不信前端 `Content-Type`）
3. MIME 在 `allowed_mime_prefixes` 任一前缀下
4. scope 累计 ≤ `per_scope_quota_mb`
5. 通过后写文件 + 写索引

**清理策略**：删除 chat_session / chatroom 时级联删除该 scope 下所有附件——在 `chat_sessions.py` / `chatrooms.py` 的 delete 处加调用。

### 6.5 消息引用

扩展 `ChatroomMessage` 与 `ChatMessage`：

```python
class ChatroomMessage(BaseModel):
    # ... 既有字段
    attachments: List[str] = Field(default_factory=list)  # attachment_id 列表
```

前端类型同步：`types/index.ts` 加 `attachments?: string[]`。

### 6.6 前端 UI

**ChatPanel + ChatroomPanel 输入区**：

```tsx
// 底部输入框旁
<div className="composer-toolbar">
  <button title="添加附件" onClick={() => fileInputRef.current?.click()}>📎</button>
  <input
    type="file"
    ref={fileInputRef}
    style={{ display: 'none' }}
    multiple
    onChange={handleFilePick}
  />
</div>

// textarea 监听 paste / dragover / drop
<textarea
  onPaste={handlePaste}     // 截图直接 Ctrl+V
  onDragOver={(e) => e.preventDefault()}
  onDrop={handleDrop}
  ...
/>

// 已选附件预览条（在发送前）
<div className="composer-attachments">
  {pending.map(att => (
    <AttachmentChip
      key={att.id}
      attachment={att}
      progress={uploadProgress[att.id]}
      onRemove={() => removePending(att.id)}
    />
  ))}
</div>
```

**上传**：用 `XMLHttpRequest` 取 `progress` 事件。多文件并发，单文件失败不阻塞其他。

**消息渲染**：

- 图片：`<img src={`/api/attachments/${id}`} />`，懒加载
- PDF：图标 + 「下载 / 在工作区打开」按钮
- 文本：图标 + 文件名 + 大小，点击下载
- ZIP：图标 + 「Agent 可见路径: workspace/.attachments/<id>」

### 6.7 Agent 消费协议

附件如何进入 Agent 上下文，按 MIME 分流：

**A. `image/*` → vision payload**

`assistant.py` / Agent 工具循环里，构造 LLM 消息时若当前用户消息有 `attachments`：

```python
for att_id in attachments:
    att = AttachmentStore().get(att_id)
    if att.mime_type.startswith("image/"):
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": att.mime_type,
                       "data": base64.b64encode(att.read_bytes()).decode()},
        })
```

OpenAI / Anthropic 多模态 SDK 都支持这个结构。

**B. `text/*` / `application/json` → 路径塞 system prompt**

```
[附件] 用户上传了 1 个文本文件，可用 read_file 工具读取：
- ./.attachments/<id>__<filename> (text/plain, 12 KB)
```

后端在 `_run_speaking_task` / `assistant.execute` 准备消息时拼这段，**只塞元数据 + 工作区相对路径**，让 Agent 自己决定要不要 `read_file`。

为此需要在 workspace 根目录下创建符号链接 `.attachments/` 指向 `data/attachments/`，让 Agent 能用工作区相对路径读到。或者更简单：直接 expose `attachment://` URI scheme，但增加新工具路径 → 优先走符号链接方案。

**C. `application/pdf` / `application/zip` → 路径 only**

同 B，让 Agent 通过 `bash` (`pdftotext` / `unzip -l`) 处理。

**D. 大文件**

> 50 MB 直接拒收（白名单 + 大小校验在 6.4 步骤 1）。如果业务有大文件需求，未来加 `attachments.large_files: enabled` + S3 后端是后话。

### 6.8 落地范围

本 spec 实施只覆盖：

- ✅ 模型 + API + 存储 + 索引
- ✅ ChatPanel / ChatroomPanel UI 上传 + 渲染
- ✅ 图片走 vision；text/* / pdf 走元数据 + 工作区符号链接
- ❌ 附件预览页（PDF in-browser viewer）— 未来
- ❌ 附件编辑 — 永远不会做
- ❌ S3 / OSS 存储后端 — 看真实需求再说

---

## 7. B4 — Agent 模型名展示

### 7.1 现状确认

`AgentInfo` 已包含 `model?: string | null` 与 `llm?: AgentLLMConfig | null`（`frontend/src/types/index.ts:84-85`）。后端 `_public_llm_config`（`main.py:305-324`）通过 `runtime_config.llm.model` 暴露，路由层照透。

### 7.2 改动

**前端纯展示**，无后端改动。

`ChatroomPanel.tsx:50-55` 的 `senderDisplayName` 单独抽出 `senderModel`：

```tsx
const agentInfoMap = useAgentInfo()  // 新 hook：从 store 取 listAgents 缓存

function renderSenderName(sender: string, agents: Map<string, AgentInfo>): ReactNode {
  if (sender === 'user') return <span>用户</span>
  if (sender === 'system') return <span>系统</span>
  if (sender.startsWith('agent:')) {
    const name = sender.slice(6) || 'agent'
    const model = agents.get(name)?.model || agents.get(name)?.llm?.model
    return (
      <span>
        {name}
        {model && <span className="agent-model-badge"> · {model}</span>}
      </span>
    )
  }
  return <span>{sender}</span>
}
```

CSS：`.agent-model-badge` 用 `color: var(--text-muted); font-size: 0.78em; font-weight: 400;` 让它视觉退后。

**ChatPanel** 同步：消息气泡发送者位置同样调用 `renderSenderName`。

**model 缺失**：默认渲染只显示 Agent 名，没有徽标。

### 7.3 新 hook 草稿

`frontend/src/hooks/useAgents.ts`（如果还没有就新加；已有就复用）：

```ts
export function useAgentInfo(): Map<string, AgentInfo> {
  const { state } = useAppStore()
  return useMemo(() => {
    const m = new Map<string, AgentInfo>()
    state.agents.forEach(a => m.set(a.name, a))
    return m
  }, [state.agents])
}
```

如果 store 里还没缓存 agents，需在 `App.tsx` 启动时 `api.listAgents()` 一次并 dispatch `SET_AGENTS`（已经有类似 pattern，见 `SET_WORKSPACES`）。

---

## 8. B5 — `ChatroomPanel` 设置面板汉化

### 8.1 现状（`ChatroomPanel.tsx:1462-1510`）

```tsx
<span>auto_host</span>
<input type="checkbox" checked={settings.auto_host} ... />

<span>host_agent</span>
<select value={settings.host_agent} ... />

<NumberField label="recent_n" ... />
<NumberField label="summary_threshold_m" ... />
<NumberField label="max_relay_depth" ... />
<NumberField label="max_members" ... />

<span>allow_agent_invite</span>
<input type="checkbox" ... />
```

### 8.2 改动

**只改前端展示，不动后端 key**。

新建 `frontend/src/components/chatroomSettingsLabels.ts`：

```ts
export const CHATROOM_SETTING_LABELS: Record<string, { label: string; hint: string }> = {
  auto_host: {
    label: '自动主持人',
    hint: '没被 @ 时，由主持 Agent 自动接话',
  },
  host_agent: {
    label: '主持 Agent',
    hint: '自动接话时由谁说，必须是房间成员',
  },
  recent_n: {
    label: '上下文条数',
    hint: '给 Agent 看的最近 N 条消息',
  },
  summary_threshold_m: {
    label: '摘要触发阈值',
    hint: '早于上下文窗口的消息累计达 M 条时自动摘要',
  },
  max_relay_depth: {
    label: '最大接力层数',
    hint: '一条消息触发的连锁 @ 最多几层，避免死循环',
  },
  max_members: {
    label: '房间成员上限',
    hint: '',
  },
  allow_agent_invite: {
    label: '允许 Agent 互相拉人',
    hint: '关闭后只有用户能拉人',
  },
  // 为 A1 / A21 预留（spec 之外）
  auto_memory: {
    label: '自动记忆',
    hint: '自动检索长期记忆并在消息生成后反思沉淀',
  },
  allow_subagent_dispatch: {
    label: '允许私下派子 Agent',
    hint: '默认关。开启后房间成员可调 dispatch_agent',
  },
}
```

UI 模板：

```tsx
<label className="chatroom-setting-row">
  <div className="chatroom-setting-label">
    <span>{CHATROOM_SETTING_LABELS.auto_host.label}</span>
    <small className="chatroom-setting-hint">
      {CHATROOM_SETTING_LABELS.auto_host.hint}
    </small>
  </div>
  <input type="checkbox" checked={settings.auto_host}
         onChange={(e) => apply({ auto_host: e.target.checked })} />
</label>
```

`NumberField` 组件签名扩展接受 `hint?: string`。

新 CSS：

```css
.chatroom-setting-row { display: flex; gap: 12px; align-items: flex-start; }
.chatroom-setting-label { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.chatroom-setting-hint { color: var(--text-muted); font-size: 0.78rem; line-height: 1.3; }
```

### 8.3 与 A1 / A21 协调

`auto_memory` / `allow_subagent_dispatch` 当前不存在于 `Chatroom.settings`；本 spec **只在 labels 表里登记**，但**不在 UI 里渲染**这两项——它们由 A1（聊天室自动记忆）/ A21（房间私派子 Agent）的独立 spec 引入。这样 A1/A21 落地时只需把对应的 `<label>` 加进 settings drawer 即可，不用再改翻译表。

---

## 9. `system.yaml` 全部新增字段汇总

便于后续迁移与文档同步。所有字段都有合理默认，不填等于关闭。

```yaml
# === A4 ===
agent_creation:
  forbidden_tools: []          # 全局禁用 tool 名单。空 = 任何工具可挂。

# === A10 ===
dispatch:
  max_depth: 5                 # dispatch_agent 嵌套上限。0=禁止嵌套, -1=无限。

# === A11 ===
server:
  access_password: ""          # 全局访问密码。空 = 不开启。

# === B1 ===
attachments:
  enabled: true                # 启用附件功能
  storage_dir: "./data/attachments"
  max_size_mb: 50
  allowed_mime_prefixes:
    - "image/"
    - "text/"
    - "application/pdf"
    - "application/json"
    - "application/zip"
    - "application/x-tar"
    - "application/gzip"
  per_scope_quota_mb: 500
```

`SystemConfig` 同步加 `AgentCreationConfig` / `DispatchConfig` / `AttachmentsConfig` / `ServerConfig.access_password` 4 个新字段。

---

## 10. 实施顺序

| 优先级 | 项 | 估计代码量 | 依赖 |
|---|---|---|---|
| **P0 — 一组并行（不互相影响，单 PR 即可）** | A8 + B4 + B5 | 前端 ~250 行 | 无后端改动 |
| **P1 — 一组并行** | A4 + A10 | 后端 ~400 行 + agents.yaml prompt | 互相独立，可同 PR |
| **P2 — 单独** | A11 | 后端 ~150 行 + 前端 ~200 行 | 影响 100% 流量，单独 PR |
| **P3 — 单独，最大** | B1 | 后端 ~600 行 + 前端 ~500 行 | 单独 PR，可拆成"上传/存储/渲染/Agent 消费"4 个子 PR |

A11 之所以单独 PR：开关一开整个 API 全要带 token，前后端必须同时部署，回滚也得整套回滚。

---

## 11. 测试策略

每项至少一条具体可执行的端到端测试。

### A4

```python
# tests/integration/test_evolution_freedom.py
async def test_agent_creator_can_grant_bash():
    """A4: agent_creator 创建带 bash 的新 Agent 不应被拒绝。"""
    cap = CreateAgentConfigCapability()
    result = await cap.execute(
        name="test_runner",
        description="跑测试",
        system_prompt="你是测试 runner",
        tools=["bash", "write_file", "dispatch_agent"],
    )
    assert result["success"] is True
    assert "bash" in result["agent"]["tools"]

async def test_forbidden_tools_block_rejects():
    """A4: forbidden_tools 配置项仍能拒绝。"""
    with patch_config({"agent_creation": {"forbidden_tools": ["bash"]}}):
        result = await cap.execute(name="x", description="y", system_prompt="z", tools=["bash"])
    assert "bash" in result["error"]
```

### A8

```ts
// frontend/src/__tests__/AgentPanel.test.tsx
test('reload button calls /api/evolution/reload and updates lastReload', async () => {
  fetchMock.mockResponseOnce(JSON.stringify({ status: 'ok' }))
  render(<AgentPanel />)
  const btn = screen.getByRole('button', { name: /重新装载/ })
  fireEvent.click(btn)
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/evolution/reload',
    expect.objectContaining({ method: 'POST' })))
  expect(screen.getByText(/上次装载/)).toBeInTheDocument()
})
```

### A10

```python
async def test_update_agent_config_no_approval_required():
    """A10: update_agent_config 调用即生效，不要 admin_approved。"""
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="assistant",
        patch={"description": "new desc"},
    )
    assert result["success"] is True
    assert result["agent"]["description"] == "new desc"

async def test_dispatch_agent_max_depth_5():
    """A10: dispatch_agent 默认允许 4 层嵌套（depth 0->1->2->3->4）。"""
    # 在 ContextVar 里手动塞 depth=4，验证能通过；depth=5 才拒。
    set_dispatch_depth(4)
    result = DispatchAgentCapability().check_permissions()
    assert result["decision"] == "allow"
    set_dispatch_depth(5)
    result = DispatchAgentCapability().check_permissions()
    assert result["decision"] == "deny"
```

### A11

```python
async def test_no_password_no_auth(client):
    """A11: access_password 空时所有请求放行。"""
    response = await client.get("/api/agents")
    assert response.status_code != 401

async def test_password_set_blocks_unauth(client_with_password):
    """A11: 设置密码后，无 Authorization 返回 401."""
    response = await client_with_password.get("/api/agents")
    assert response.status_code == 401
    assert response.json()["error"] == "auth_required"

async def test_password_lockout_after_5_fails(client_with_password):
    """A11: 同 IP 5 次失败后 60s 锁定。"""
    for _ in range(5):
        await client_with_password.get("/api/agents",
            headers={"Authorization": "Bearer wrong"})
    response = await client_with_password.get("/api/agents",
        headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 429
    assert response.json()["error"] == "auth_locked"

async def test_health_endpoint_open(client_with_password):
    """A11: /api/health 永远不要门禁。"""
    response = await client_with_password.get("/api/health")
    assert response.status_code == 200
```

### B1

```python
async def test_upload_image_accepted(client):
    files = {"file": ("hello.png", b"\x89PNG\r\n\x1a\n...", "image/png")}
    response = await client.post("/api/attachments?scope=chatroom:test", files=files)
    assert response.status_code == 200
    att_id = response.json()["data"]["id"]
    download = await client.get(f"/api/attachments/{att_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/png"

async def test_upload_oversize_rejected(client):
    """B1: 超过 max_size_mb 拒绝。"""
    big = b"x" * (60 * 1024 * 1024)  # 60 MB
    response = await client.post("/api/attachments?scope=test",
        files={"file": ("big.bin", big, "application/octet-stream")})
    assert response.status_code == 413

async def test_chatroom_message_with_image_triggers_vision():
    """B1: 图片附件应被拼成 vision content block 进入 Agent 消息。"""
    # mock LLM client，断言 messages 里包含 type=image block
```

### B4

```ts
test('chatroom agent message shows model badge', () => {
  const msg = { sender: 'agent:reviewer', content: 'hello' }
  const agents = new Map([['reviewer', { name: 'reviewer', model: 'gpt-4o' }]])
  render(<MessageBubble msg={msg} agents={agents} />)
  expect(screen.getByText('reviewer')).toBeInTheDocument()
  expect(screen.getByText(/gpt-4o/)).toHaveClass('agent-model-badge')
})
```

### B5

```ts
test('chatroom settings drawer shows Chinese labels', () => {
  render(<ChatroomSettingsDrawer settings={defaultSettings} />)
  expect(screen.getByText('自动主持人')).toBeInTheDocument()
  expect(screen.getByText(/没被 @ 时，由主持 Agent 自动接话/)).toBeInTheDocument()
  expect(screen.queryByText('auto_host')).toBeNull()
})
```

---

## 12. 安全考虑

### 12.1 A10 / A4：审批换审计的边界

**保留的安全网（不要再被反向拆掉）**：

1. **字段白名单**：`ALLOWED_AGENT_FIELDS` 仍要校验，防止 patch 注入未知字段。
2. **路径越权**：`_validate_skill_paths` / `_validate_default_workspace_root` 保留。
3. **密钥脱敏**：API key 仍走 `_sanitize_agent_config`，不让 LLM 输出泄露。
4. **PROTECTED_AGENT_NAMES**：防止 `agent_creator` 用 `create_agent_config` 覆盖原生 Agent。
5. **reload 失败回滚**：`_reload_or_rollback` 是数据完整性，不是审批。

**可追溯性**：

- 所有 `update_*` 写操作前后强制 `structlog.info(...)`，字段含 `caller_task_id` / `agent_name` / `changed_fields` / `timestamp`。
- 所有 yaml 改动通过 `save_yaml_config` 落盘，git diff 可见。
- Phase 2 候选：写完 yaml 自动 git commit，author 标 `task:<id>`。本 spec 不做。

**真正的攻击面变化**：

| 方面 | 改前 | 改后 |
|---|---|---|
| 误操作 Agent | 闸门拦 | 写日志 + git revert |
| Agent 自我提权（挂高危工具） | 闸门拦，但闸门形同虚设（Agent 自填 admin_approved=true） | 默认允许，`forbidden_tools` 想锁可锁 |
| Agent 写出恶意 yaml | 字段白名单 + 路径校验 | **不变**，保留 |
| 攻击者通过 Agent 跑 bash | 取决于 bash 工具自身的 sandbox | **不变**，本 spec 不动 bash 工具 |

净结果：误操作风险略升（用 git 兜底），合法能力大幅放开。这是单机本地 Agent 系统的合理权衡。

### 12.2 A11：密码门禁的强度边界

**做了什么**：

- 中间件级 401，HTTP/WS 都过；
- IP 失败计数 + 60s 锁定；
- `hmac.compare_digest` 防时序攻击；
- WS 用 `?token=` query 参数（也是行业惯用法，避免 WebSocket 协议没有 Authorization header）。

**没做什么 + 风险**：

| 缺项 | 风险 | 缓解 |
|---|---|---|
| HTTPS | 明文密码可被中间人截获 | **必须**部署在 HTTPS 后（nginx / Caddy / Cloudflare） |
| 密码哈希 | system.yaml 落盘明文 | 最低限度：`chmod 600 config/system.yaml`；最佳：用环境变量 `ACCESS_PASSWORD` 优先级 > yaml |
| 单独账号 | 多人共用同一密码 | 用户拒绝；后续如有多人需求再升级 |
| Token 过期 | 一次输入永久 | logout 按钮 = clearToken；换密码 = 改 yaml + 重启 |
| WS query token 泄露日志 | 反向代理日志可能记录 query string | 反向代理配置 `access_log off` 或 mask query |

**WS 关闭码 4401 的选择**：4000-4999 是 WebSocket 协议给应用层的自定义关闭码区间；4401 借 HTTP 401 的语义，前端识别简单。

### 12.3 B1：附件存储的安全

| 风险 | 缓解 |
|---|---|
| 路径穿越（filename 含 `../`） | `safe_filename = re.sub(r'[^\w.\-]', '_', filename)` + 用 attachment_id 拼绝对路径 |
| MIME spoofing（前端伪造 Content-Type） | 后端用 `python-magic` 重测；只信探测结果 |
| 超大文件 DoS | `max_size_mb` + `per_scope_quota_mb` |
| 上传脚本（`.sh` / `.exe`） | 白名单 prefix 过滤；`application/x-shellscript` 不在列表里 |
| 攻击者伪造 scope | `scope` 必须能被服务端解析为合法的 chat_session/chatroom；不存在的 scope 拒收 |
| Agent 通过 read_file 读到附件 | 这是预期行为，但要确保 read_file 仍走 workspace 根校验，不能读到 `../data/attachments/<别人的 scope>` |

**符号链接方案的弱点**：Windows 默认不允许 mklink 给普通用户。Phase 1 在 Windows 落地时改成在 workspace 下复制一份附件（牺牲存储），或扩展 read_file 工具支持 `attachment://` URI。

### 12.4 通用：日志中不打印密码 / token / api_key

- `print` / `logger.info` 调用前对 kwargs 做 mask（既有 `_sanitize_agent_config` / `MASKED_API_KEY_VALUES` 模式可复用）。
- `BaseHTTPMiddleware` 不要日志原始 Authorization header 值；记 `len(token)` 即可。

---

## 13. 后续协调

落地后需同步更新：

- `agentic-system/CLAUDE.md` §5 API 端点表 — 加 `/api/attachments/*`
- `agentic-system/CLAUDE.md` §3.10 聊天室章节 — `Chatroom.settings` 新增 attachments 引用
- `agentic-system/CLAUDE.md` §4.1/§4.3 配置体系 — `system.yaml` 新字段
- `agentic-system/docs/api.md` — 同步附件接口 + 鉴权 header 要求
- 「3 月 17 日开题报告」/ 「文献综述」 — 把"防御式审批闸门"列为本系统的设计反例。

---

**文档状态**: v1.0 — 设计阶段
**下一步**: 用户确认后按 §10 顺序拆 PR 实施
