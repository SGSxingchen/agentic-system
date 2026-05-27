# 自由化与 UI 增强实施计划 — 2026-05-28

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 spec 2026-05-28-liberalization-and-ui-design.md 的 7 项改动落地：A4/A10 拆审批闸门换审计；A8 reload 按钮；A11 全局密码；B1 附件全栈；B4 模型徽标；B5 设置面板汉化。

**Architecture:** 4 个优先级阶段（P0 UI 小项并行 → P1 后端自由化并行 → P2 密码门禁 → P3 附件大节）。所有写操作统一加 `structlog.info("config_change", ...)` 审计；不引入新框架；FastAPI 中间件 + axios 拦截器 + Vite 既有能力。

**Tech Stack:** Python 3.10+ / FastAPI / pytest / pytest-asyncio / structlog / React 18 / TypeScript 5 / Vite 5 / fetch API

---

## 风险点与预先决策（实施前必读）

来自 spec 子 Agent 在调研中发现的额外问题，每条都已映射到具体 task：

- **R1 — `HIGH_RISK_TOOLS` 重复定义**：`evolution_config.py:27-33` 与 `agent_management.py:40-46` 都有一份。Task 4 必须**先合并到一处**（`core/capability/registry.py` 或新建 `core/capability/risk.py`），再删除。否则一处删掉另一处仍生效，A4 会半失效。
- **R2 — `propose_*` / `apply_*` 工具收敛**：spec §4.2 把 `propose_agent_config_patch` + `apply_agent_config_patch` 合并成单一 `update_agent_config`；persona 同理。Task 8/9/10 必须按"动作动词不再 propose/patch/approve"原则统一动词。
- **R3 — WebSocket 鉴权用 query 参数 + close code 4401**：WS 协议无 `Authorization` header。Task 16 实现走 `?token=xxx` + 自定义 close 4401。
- **R4 — WS query string 在反代 access_log 暴露**：Task 17 写一份 nginx 配置示例放 `docs/deployment.md`，提示 mask `?token=`。
- **R5 — 附件 vision payload 路径**：图片走 OpenAI/Anthropic vision multipart；非图片附件路径塞进 system prompt + Agent 用 `read_file` 读。Task 26-28 区分两条路径。
- **R6 — 附件路径符号链接 Windows 不支持**：Task 24 落地"workspace 引用 attachments"时，Windows 下走文件复制 fallback；symlink 是 Linux 优化。
- **R7 — `PersonaStore.list_proposals` 存量 pending 数据**：A10 改完不删存量，前端 `PersonaPanel` 改"历史/归档"语义。Task 12 处理。
- **R8 — 自动化 git commit 推到 Phase 2**：审计先靠 `structlog.info`，不强求 git auto-commit；spec §1 已注明。

---

## 阶段总览

| Phase | 任务范围 | Task # |
|---|---|---|
| **P0** | UI 小项并行 (A8 + B4 + B5) | 1-3 |
| **P1** | 后端自由化并行 (A4 + A10) | 4-13 |
| **P2** | 全局访问密码 (A11) | 14-19 |
| **P3** | 附件支持 (B1) | 20-30 |
| **末** | 文档同步 + 集成测试 | 31-32 |

---

# Phase P0 — UI 小项（独立可并行）

### Task 1: B5 — 设置面板字段汉化

**Files:**
- Modify: `frontend/src/components/ChatroomPanel.tsx:1462-1510`
- Modify: `frontend/src/components/ChatroomPanel.css`（如需新加 `.chatroom-settings__hint` 类）
- Test: `frontend/src/__tests__/ChatroomPanel.test.tsx`（新建或追加）

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/__tests__/ChatroomPanel.test.tsx
test('B5: settings labels are localized', () => {
  const room = { id: 'r1', settings: { auto_host: false, host_agent: 'planner', recent_n: 30, summary_threshold_m: 20, max_relay_depth: 3, max_members: 10, allow_agent_invite: true }, members: ['planner'], ...stubFields }
  render(<SettingsForm settings={room.settings} agents={['planner']} onUpdate={() => {}} />)
  expect(screen.getByText('自动主持人')).toBeInTheDocument()
  expect(screen.getByText('主持 Agent')).toBeInTheDocument()
  expect(screen.getByText('上下文条数')).toBeInTheDocument()
  expect(screen.getByText('摘要触发阈值')).toBeInTheDocument()
  expect(screen.getByText('最大接力层数')).toBeInTheDocument()
  expect(screen.getByText(/没被.*@.*时.*主持/)).toBeInTheDocument()  // 副说明
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run ChatroomPanel`
Expected: FAIL（找不到中文 label）

- [ ] **Step 3: 实现汉化**

替换 `ChatroomPanel.tsx:1462-1510` 那段 SettingsForm 的所有 `<span>auto_host</span>` 风格为：

```tsx
<label className="chatroom-settings__row">
  <div className="chatroom-settings__label">
    <span>自动主持人</span>
    <small className="chatroom-settings__hint">没被 @ 时，自动让主持 Agent 接话</small>
  </div>
  <input type="checkbox" checked={settings.auto_host} onChange={(e) => apply({ auto_host: e.target.checked })} />
</label>
```

完整对应表（写在文件顶部 `const SETTING_LABELS`）：

```tsx
const SETTING_LABELS: Record<string, { label: string; hint: string }> = {
  auto_host: { label: '自动主持人', hint: '没被 @ 时，自动让主持 Agent 接话' },
  host_agent: { label: '主持 Agent', hint: '自动接话时由谁说，必须是房间成员' },
  recent_n: { label: '上下文条数', hint: '给 Agent 看的最近 N 条消息' },
  summary_threshold_m: { label: '摘要触发阈值', hint: '早于上下文窗口的消息累计达 M 条时自动摘要' },
  max_relay_depth: { label: '最大接力层数', hint: '一条消息触发的连锁 @ 最多几层，避免死循环' },
  max_members: { label: '房间成员上限', hint: '' },
  allow_agent_invite: { label: '允许 Agent 互相拉人', hint: '关闭后只有用户能拉人' },
  auto_memory: { label: '自动记忆', hint: 'Spec 1 A1：自动检索长期记忆并在消息生成后反思沉淀' },
  allow_subagent_dispatch: { label: '允许私下派子 Agent', hint: 'Spec 2 A21：默认关。开启后房间成员可调 dispatch_agent' },
}
```

后端 key 一律不动。

- [ ] **Step 4: 跑测试通过 + 视觉检查**

Run: `cd frontend && npx vitest run ChatroomPanel`
Expected: PASS

启 dev server 实际看一眼设置抽屉。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatroomPanel.tsx frontend/src/components/ChatroomPanel.css frontend/src/__tests__/ChatroomPanel.test.tsx
git commit -m "feat(ui): B5 房间设置面板字段汉化 + 副说明"
```

---

### Task 2: B4 — Agent 名后挂模型徽标

**Files:**
- Verify: `backend/src/api/routes/agents.py`（确认 `/api/agents` 返回 model 字段）
- Modify: `frontend/src/types/index.ts`（Agent type 加 `model?: string`）
- Modify: `frontend/src/components/ChatroomPanel.tsx`（`senderDisplayName` 函数）
- Modify: `frontend/src/components/ChatPanel.tsx`（同步）
- Modify: `frontend/src/components/ChatroomPanel.css` / `ChatPanel.css`（新增 `.agent-model-badge`）
- Test: `frontend/src/__tests__/AgentBadge.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
test('B4: agent message header shows model badge', () => {
  const message = { id: 'm1', sender: 'agent:reviewer', content: '...', status: 'done' }
  const agentMeta = { reviewer: { model: 'gpt-4o', name: 'reviewer' } }
  render(<MessageHeader message={message} agentMeta={agentMeta} />)
  expect(screen.getByText('reviewer')).toBeInTheDocument()
  expect(screen.getByText('gpt-4o')).toHaveClass('agent-model-badge')
})

test('B4: missing model gracefully degrades to name only', () => {
  const message = { id: 'm1', sender: 'agent:custom', content: '...', status: 'done' }
  render(<MessageHeader message={message} agentMeta={{}} />)
  expect(screen.getByText('custom')).toBeInTheDocument()
  expect(screen.queryByClassName('agent-model-badge')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run AgentBadge`
Expected: FAIL

- [ ] **Step 3: 实现 hook + 渲染**

在 `frontend/src/hooks/useAgents.ts`（如不存在则新建）暴露 `agentMeta: Record<string, { name: string; model?: string }>` map，从 `/api/agents` 拉取。

修改 `ChatroomPanel.tsx`：

```tsx
function senderDisplayName(sender: string, agentMeta: AgentMetaMap): { name: string; model?: string } {
  if (sender === 'user') return { name: '用户' }
  if (sender === 'system') return { name: '系统' }
  if (sender.startsWith('agent:')) {
    const name = sender.slice(6) || 'agent'
    return { name, model: agentMeta[name]?.model }
  }
  return { name: sender || 'unknown' }
}
```

渲染处：

```tsx
const display = senderDisplayName(message.sender, agentMeta)
return (
  <span className="chatroom-msg__sender">
    {display.name}
    {display.model && <small className="agent-model-badge">{display.model}</small>}
  </span>
)
```

CSS：

```css
.agent-model-badge {
  display: inline-block;
  margin-left: 0.4em;
  padding: 0 0.4em;
  font-size: 0.75em;
  color: var(--color-fg-subtle);
  background: var(--color-bg-subtle);
  border-radius: 0.25em;
}
```

ChatPanel.tsx 同步改造。

- [ ] **Step 4: 跑测试通过**

Run: `cd frontend && npx vitest run AgentBadge`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/hooks/useAgents.ts \
  frontend/src/components/ChatroomPanel.tsx frontend/src/components/ChatPanel.tsx \
  frontend/src/components/ChatroomPanel.css frontend/src/components/ChatPanel.css \
  frontend/src/__tests__/AgentBadge.test.tsx
git commit -m "feat(ui): B4 Agent 名后展示模型徽标"
```

---

### Task 3: A8 — AgentPanel 顶部"重新装载"按钮

**Files:**
- Verify: `backend/src/api/routes/evolution.py` 已有 `POST /api/evolution/reload`
- Modify: `frontend/src/components/AgentPanel.tsx`（顶部加按钮 + 状态）
- Modify: `frontend/src/components/AgentPanel.css`
- Test: `frontend/src/__tests__/AgentPanel.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
test('A8: reload button calls /api/evolution/reload and updates lastReload', async () => {
  fetchMock.mockResponseOnce(JSON.stringify({ status: 'ok', reloaded_at: '2026-05-28T01:00:00Z' }))
  render(<AgentPanel />)
  const btn = screen.getByRole('button', { name: /重新装载/ })
  fireEvent.click(btn)
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    '/api/evolution/reload',
    expect.objectContaining({ method: 'POST' })
  ))
  expect(screen.getByText(/上次装载/)).toBeInTheDocument()
})

test('A8: reload button shows loading state', async () => {
  fetchMock.mockResponseOnce(() => new Promise(resolve => setTimeout(() => resolve({ body: '{}' }), 500)))
  render(<AgentPanel />)
  fireEvent.click(screen.getByRole('button', { name: /重新装载/ }))
  expect(screen.getByText(/装载中/)).toBeInTheDocument()
})

test('A8: reload error displays clearly', async () => {
  fetchMock.mockResponseOnce(JSON.stringify({ error: 'reload failed' }), { status: 500 })
  render(<AgentPanel />)
  fireEvent.click(screen.getByRole('button', { name: /重新装载/ }))
  await waitFor(() => expect(screen.getByText(/装载失败/)).toBeInTheDocument())
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run AgentPanel`
Expected: FAIL（按钮不存在）

- [ ] **Step 3: 实现按钮**

在 `AgentPanel.tsx` 顶部加：

```tsx
const [reloading, setReloading] = useState(false)
const [lastReload, setLastReload] = useState<string | null>(null)
const [error, setError] = useState<string | null>(null)

async function handleReload() {
  setReloading(true)
  setError(null)
  try {
    const res = await fetch('/api/evolution/reload', { method: 'POST' })
    if (!res.ok) throw new Error('装载失败')
    const data = await res.json()
    setLastReload(data.reloaded_at || new Date().toISOString())
  } catch (e: any) {
    setError(e.message || '装载失败')
  } finally {
    setReloading(false)
  }
}

return (
  <div className="agent-panel">
    <div className="agent-panel__header">
      <button onClick={handleReload} disabled={reloading} className="agent-panel__reload-btn">
        {reloading ? '装载中…' : '重新装载'}
      </button>
      {lastReload && <small>上次装载：{new Date(lastReload).toLocaleString()}</small>}
      {error && <small className="agent-panel__error">{error}</small>}
    </div>
    {/* 其余原有内容 */}
  </div>
)
```

- [ ] **Step 4: 跑测试通过**

Run: `cd frontend && npx vitest run AgentPanel`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentPanel.tsx frontend/src/components/AgentPanel.css frontend/src/__tests__/AgentPanel.test.tsx
git commit -m "feat(ui): A8 AgentPanel 顶部加重新装载按钮"
```

---

# Phase P1 — 后端自由化（A4 + A10 并行）

### Task 4: 合并重复的 HIGH_RISK_TOOLS 常量（R1 预处理）

**Files:**
- Create: `backend/src/core/capability/risk.py`
- Modify: `backend/src/capabilities/tools/evolution_config.py:27-33`（删除常量，改 import）
- Modify: `backend/src/capabilities/tools/agent_management.py:40-46`（同上）
- Test: `backend/tests/unit/test_capability_risk.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_capability_risk.py
from src.core.capability.risk import HIGH_RISK_TOOLS, AGENT_MANAGEMENT_TOOLS

def test_high_risk_tools_is_single_source_of_truth():
    assert "bash" in HIGH_RISK_TOOLS
    assert "write_file" in HIGH_RISK_TOOLS
    assert "create_agent_config" in HIGH_RISK_TOOLS
    assert "create_dynamic_tool_config" in HIGH_RISK_TOOLS
    assert "dispatch_agent" in HIGH_RISK_TOOLS

def test_agent_management_tools_is_single_source():
    assert "propose_agent_config_patch" in AGENT_MANAGEMENT_TOOLS

def test_no_duplicate_definitions():
    """grep 项目代码，HIGH_RISK_TOOLS 只能在 risk.py 里 = {...} 赋值。"""
    import subprocess
    result = subprocess.run(
        ["grep", "-rn", "HIGH_RISK_TOOLS = {", "backend/src/"],
        capture_output=True, text=True,
    )
    lines = [l for l in result.stdout.splitlines() if l]
    assert len(lines) == 1, f"Found duplicates: {lines}"
    assert "core/capability/risk.py" in lines[0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/unit/test_capability_risk.py -v`
Expected: FAIL（重复定义还在）

- [ ] **Step 3: 创建集中常量 + 修改 import**

```python
# backend/src/core/capability/risk.py
"""High-risk capability identifiers used by capability gating logic.

Centralized definitions to avoid duplicate constants in tool files.
After A4/A10, these are advisory — actual gating moves to system.yaml
forbidden_tools / dispatch.max_depth knobs.
"""

HIGH_RISK_TOOLS = frozenset({
    "bash",
    "write_file",
    "create_agent_config",
    "create_dynamic_tool_config",
    "dispatch_agent",
})

AGENT_MANAGEMENT_TOOLS = frozenset({
    "propose_agent_config_patch",
    "apply_agent_config_patch",
    "list_agent_proposals",
    "get_agent_proposal",
})
```

`evolution_config.py` 顶部：

```python
from src.core.capability.risk import HIGH_RISK_TOOLS  # 替代行 27-33
```

`agent_management.py` 同理。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/unit/test_capability_risk.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/core/capability/risk.py \
  backend/src/capabilities/tools/evolution_config.py \
  backend/src/capabilities/tools/agent_management.py \
  backend/tests/unit/test_capability_risk.py
git commit -m "refactor: 合并 HIGH_RISK_TOOLS 重复定义到 core/capability/risk.py"
```

---

### Task 5: A4 — `system.yaml` escape hatch

**Files:**
- Modify: `config/system.yaml`
- Modify: `backend/src/core/config.py`（如需要 schema）
- Test: `backend/tests/unit/test_system_config.py`

- [ ] **Step 1: 写失败测试**

```python
def test_agent_creation_forbidden_tools_default_empty():
    cfg = load_system_config()
    assert cfg.agent_creation.forbidden_tools == []

def test_agent_creation_forbidden_tools_loaded_from_yaml(tmp_path):
    yaml_content = """
agent_creation:
  forbidden_tools: [bash, dispatch_agent]
"""
    (tmp_path / "system.yaml").write_text(yaml_content)
    cfg = load_system_config(config_dir=tmp_path)
    assert cfg.agent_creation.forbidden_tools == ["bash", "dispatch_agent"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/unit/test_system_config.py::test_agent_creation_forbidden_tools_default_empty -v`
Expected: FAIL

- [ ] **Step 3: 加 yaml 字段 + Pydantic schema**

```yaml
# config/system.yaml — 新增段
agent_creation:
  forbidden_tools: []   # 默认空，部署方可以填如 [bash] 锁住特定工具
```

`backend/src/core/config.py` 加：

```python
class AgentCreationConfig(BaseModel):
    forbidden_tools: list[str] = Field(default_factory=list)

class SystemConfig(BaseModel):
    # ... existing fields
    agent_creation: AgentCreationConfig = Field(default_factory=AgentCreationConfig)
```

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/unit/test_system_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/system.yaml backend/src/core/config.py backend/tests/unit/test_system_config.py
git commit -m "feat(config): A4 system.yaml 加 agent_creation.forbidden_tools escape hatch"
```

---

### Task 6: A4 — 删除 `evolution_config.py` 高风险拒绝逻辑

**Files:**
- Modify: `backend/src/capabilities/tools/evolution_config.py:331-339`（删除拒绝分支）
- Modify: 同文件，使用新 `forbidden_tools` 配置
- Test: `backend/tests/integration/test_evolution_freedom.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_evolution_freedom.py
async def test_agent_creator_can_grant_bash():
    """A4: agent_creator 创建带 bash 的新 Agent 不应被拒绝。"""
    cap = CreateAgentConfigCapability()
    result = await cap.execute(
        name="test_runner_a4",
        description="跑测试",
        system_prompt="你是测试 runner",
        tools=["bash", "write_file", "dispatch_agent"],
    )
    assert result["success"] is True
    assert "bash" in result["agent"]["tools"]

async def test_forbidden_tools_block_rejects(monkeypatch):
    """A4: forbidden_tools 配置项仍能拒绝。"""
    monkeypatch.setattr("src.core.config.get_system_config", lambda: types.SimpleNamespace(
        agent_creation=types.SimpleNamespace(forbidden_tools=["bash"])
    ))
    cap = CreateAgentConfigCapability()
    result = await cap.execute(name="x", description="y", system_prompt="z", tools=["bash"])
    assert "forbidden" in result.get("error", "").lower() or "bash" in result.get("error", "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/integration/test_evolution_freedom.py -v`
Expected: FAIL（当前还在拒绝 bash）

- [ ] **Step 3: 改造 evolution_config.py**

删除 `:331-339` 的整个拒绝分支：

```python
# 删除：
if high_risk_tools:
    return {"error": "create_agent_config cannot grant high-risk tools..."}
```

替换为：

```python
from src.core.config import get_system_config

forbidden = set(get_system_config().agent_creation.forbidden_tools)
if forbidden:
    blocked = sorted(set(tools) & forbidden)
    if blocked:
        return {"error": f"以下工具被 system.yaml agent_creation.forbidden_tools 屏蔽：{blocked}"}
```

并加审计日志：

```python
import structlog
log = structlog.get_logger(__name__)

# 写入前
log.info("config_change", action="create_agent", agent=name, tools=tools, caller_task_id=...)
```

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/integration/test_evolution_freedom.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/capabilities/tools/evolution_config.py backend/tests/integration/test_evolution_freedom.py
git commit -m "feat: A4 删除 create_agent_config 高风险硬拒绝，改为 system.yaml escape hatch"
```

---

### Task 7: A4 — agent_creator prompt 改为"主动挂工具"

**Files:**
- Modify: `config/agents.yaml` — 找到 `agent_creator` 条目，修改 system_prompt
- 不动其他 Agent 条目（红线规则）
- Test: 手工集成

- [ ] **Step 1: 写测试（grep 风格断言）**

```python
def test_agent_creator_prompt_encourages_full_toolstack():
    import yaml
    with open("config/agents.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    creator = next(a for a in data["agents"] if a["name"] == "agent_creator")
    prompt = creator["system_prompt"]
    assert "主动" in prompt or "完整工具栈" in prompt
    assert "bash" in prompt and "write_file" in prompt
    assert "保守" not in prompt or "不要保守" in prompt
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/integration/test_agent_creator_prompt.py -v`
Expected: FAIL（旧 prompt 没"主动"关键词）

- [ ] **Step 3: 修改 agent_creator prompt**

在 `config/agents.yaml` 的 `agent_creator` 条目，把现有 system_prompt 中关于"高风险工具"的保守表述替换为：

```yaml
agent_creator:
  system_prompt: |
    你是 agent_creator —— Agent 工厂。每个 Agent 都该装齐它干活需要的工具，不要保守。
    
    工具挂载策略：
    - 根据被创建 Agent 的实际职责，主动挂上必要的工具
    - 默认每个非纯规划 Agent 都该有：read_file / write_file / file_search / web_fetch / web_search /
      bash / dispatch_agent / json_tool / text_processor / datetime_tool / calculator / memory_search
    - 纯规划 Agent（如 planner）可酌情移除 bash / write_file
    - 看到职责描述明确包含"装载 Skill / 联网下载 / 跑命令" → 必挂 bash + write_file
    
    禁止行为：
    - 不要因为"安全"而少挂工具，安全靠 system.yaml forbidden_tools 配置，不靠你
    - 不要让用户事后手动改 yaml 加工具，那是失败设计
```

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/integration/test_agent_creator_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/agents.yaml backend/tests/integration/test_agent_creator_prompt.py
git commit -m "feat: A4 agent_creator prompt 改为主动挂全套工具，不畏缩"
```

---

### Task 8: A10 — 新工具 `update_agent_config`（替代 propose+apply）

**Files:**
- Create: `backend/src/capabilities/tools/update_agent_config.py`
- Modify: `backend/src/capabilities/tools/agent_management.py:124-136`（删除 `_admin_decision`）
- Modify: `backend/src/capabilities/tools/agent_management.py:323-330`（删除 management 工具挂载限制）
- Test: `backend/tests/unit/test_update_agent_config.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_update_agent_config_no_approval_required():
    """A10: update_agent_config 调用即生效，不要 admin_approved。"""
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="assistant",
        patch={"description": "new desc by automation"},
    )
    assert result["success"] is True
    assert result["agent"]["description"] == "new desc by automation"

async def test_update_agent_config_writes_audit_log(caplog):
    cap = UpdateAgentConfigCapability()
    await cap.execute(agent_name="assistant", patch={"description": "x"})
    logged = [r for r in caplog.records if r.message == "config_change"]
    assert len(logged) >= 1
    assert logged[0].agent == "assistant"

async def test_update_agent_config_can_modify_tools():
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="assistant",
        patch={"tools": ["read_file", "write_file", "bash"]},
    )
    assert result["success"] is True
    assert "bash" in result["agent"]["tools"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/unit/test_update_agent_config.py -v`
Expected: FAIL

- [ ] **Step 3: 实现新工具**

```python
# backend/src/capabilities/tools/update_agent_config.py
"""update_agent_config — A10 调用即生效的 Agent 配置更新工具。

替代旧的 propose_agent_config_patch + apply_agent_config_patch 两段式。
"""
from typing import Any, Dict
import structlog
import yaml

from src.core.capability.base import CapabilityBase
from src.core.config import save_yaml_config

log = structlog.get_logger(__name__)


class UpdateAgentConfigCapability(CapabilityBase):
    name = "update_agent_config"
    description = (
        "直接更新某 Agent 的配置（description / system_prompt / tools / llm 等），调用即生效。"
        "审批语义已移除：所有写操作进 audit log，回溯靠 git。"
    )
    parameters = {
        "agent_name": {"type": "string", "required": True},
        "patch": {
            "type": "object",
            "required": True,
            "description": "要 merge 进 agent config 的字段",
        },
    }

    async def execute(self, agent_name: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        from src.api.dependencies import get_agent_registry
        registry = get_agent_registry()
        if not registry.has(agent_name):
            return {"success": False, "error": f"agent '{agent_name}' not found"}
        
        # 读 yaml → patch → 写回
        with open("config/agents.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        for agent in data["agents"]:
            if agent["name"] == agent_name:
                old = dict(agent)
                agent.update(patch)
                save_yaml_config("config/agents.yaml", data)
                log.info(
                    "config_change",
                    action="update_agent",
                    agent=agent_name,
                    diff=patch,
                    old_keys=list(old.keys()),
                )
                return {"success": True, "agent": agent}
        
        return {"success": False, "error": f"agent '{agent_name}' not in yaml"}
```

删除 `agent_management.py:124-136 _admin_decision`、`:323-330` 限制 management 工具到 agent_manager。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/unit/test_update_agent_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/capabilities/tools/update_agent_config.py \
  backend/src/capabilities/tools/agent_management.py \
  backend/tests/unit/test_update_agent_config.py
git commit -m "feat: A10 新增 update_agent_config 调用即生效；删除 _admin_decision 闸门"
```

---

### Task 9: A10 — 删除 `propose_agent_config_patch` + `apply_agent_config_patch`

**Files:**
- Modify: `backend/src/capabilities/tools/agent_management.py`（删除 `propose/apply` 两个 capability 类 + 注册）
- Modify: `config/agents.yaml`（agent_manager 工具列表里把 `propose_agent_config_patch` 换成 `update_agent_config`）
- Test: `backend/tests/unit/test_agent_management_legacy_removed.py`

- [ ] **Step 1: 写失败测试**

```python
def test_propose_apply_capabilities_removed():
    from src.capabilities.tools import agent_management
    assert not hasattr(agent_management, "ProposeAgentConfigPatchCapability")
    assert not hasattr(agent_management, "ApplyAgentConfigPatchCapability")

def test_agent_manager_uses_new_tool():
    import yaml
    with open("config/agents.yaml") as f:
        data = yaml.safe_load(f)
    mgr = next(a for a in data["agents"] if a["name"] == "agent_manager")
    assert "update_agent_config" in mgr["tools"]
    assert "propose_agent_config_patch" not in mgr["tools"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/unit/test_agent_management_legacy_removed.py -v`
Expected: FAIL

- [ ] **Step 3: 删除旧工具**

`agent_management.py`：
- 删除 `class ProposeAgentConfigPatchCapability` 整个类（约 200 行）
- 删除 `class ApplyAgentConfigPatchCapability` 整个类
- 删除 `class ListAgentProposalsCapability`、`class GetAgentProposalCapability`
- 删除 module-level 的 `_admin_decision` / `_validate_patch` / `_proposal_store` 等仅服务于上述类的辅助函数
- 保留 `class ListAgentsCapability` / `class GetAgentCapability`（纯读取工具，无审批）

`config/agents.yaml`：
- agent_manager 的 tools 列表 `propose_agent_config_patch` → `update_agent_config`
- 删除 `apply_agent_config_patch` / `list_agent_proposals` / `get_agent_proposal`（如果在）

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/unit/test_agent_management_legacy_removed.py tests/integration/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/capabilities/tools/agent_management.py config/agents.yaml \
  backend/tests/unit/test_agent_management_legacy_removed.py
git commit -m "refactor: A10 删除 propose+apply 两段式审批，改用 update_agent_config 单动作"
```

---

### Task 10: A10 — `update_persona` 替代 `propose_persona_evolution` + `approve_proposal`

**Files:**
- Create: `backend/src/capabilities/tools/update_persona.py`
- Modify: `backend/src/capabilities/tools/persona_evolution.py`（删除 propose/approve 两类 + `_admin_decision`）
- Modify: `backend/src/capabilities/tools/persona_management.py:19-33`（删除 admin_approved 校验）
- Test: `backend/tests/unit/test_update_persona.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_update_persona_no_approval():
    cap = UpdatePersonaCapability()
    result = await cap.execute(persona_id="default", patch={"tone": "warm"})
    assert result["success"] is True

async def test_persona_management_no_admin_token():
    """A10: persona_management 不再要求 admin_token。"""
    cap = SetPersonaCapability()  # 假设这是被改的工具
    result = await cap.execute(persona_id="x", values={"foo": "bar"})
    assert result.get("permission_denied") is not True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/unit/test_update_persona.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 + 删除旧逻辑**

类似 Task 8 的模式，新建 `update_persona.py`；删除 persona_evolution.py 的 `_admin_decision`、`ProposePersonaEvolutionCapability`、`ApproveProposalCapability`；删除 persona_management.py 行 19-33 的 admin 校验。

`PersonaStore.list_proposals` 保留（不删存量数据，前端展示成"历史/归档"，对应 R7）。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/unit/test_update_persona.py tests/integration/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/capabilities/tools/update_persona.py \
  backend/src/capabilities/tools/persona_evolution.py \
  backend/src/capabilities/tools/persona_management.py \
  backend/tests/unit/test_update_persona.py
git commit -m "refactor: A10 update_persona 替代 propose+approve 两段式 persona 流程"
```

---

### Task 11: A10 — `dispatch_agent.max_depth=1 → 5` + system.yaml 配置

**Files:**
- Modify: `backend/src/capabilities/tools/dispatch_agent.py:120`
- Modify: `config/system.yaml`（加 `dispatch.max_depth: 5`）
- Modify: `backend/src/core/config.py`（DispatchConfig schema）
- Test: `backend/tests/unit/test_dispatch_agent.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
async def test_dispatch_agent_max_depth_default_5():
    """A10: dispatch_agent 默认允许 4 层嵌套。"""
    set_dispatch_depth(4)
    permit = DispatchAgentCapability().check_permissions()
    assert permit["decision"] == "allow"
    
    set_dispatch_depth(5)
    permit = DispatchAgentCapability().check_permissions()
    assert permit["decision"] == "deny"

async def test_dispatch_max_depth_configurable(monkeypatch):
    monkeypatch.setattr("src.core.config.get_system_config", lambda: types.SimpleNamespace(
        dispatch=types.SimpleNamespace(max_depth=2)
    ))
    set_dispatch_depth(2)
    permit = DispatchAgentCapability().check_permissions()
    assert permit["decision"] == "deny"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/unit/test_dispatch_agent.py::test_dispatch_agent_max_depth_default_5 -v`
Expected: FAIL（max_depth=1）

- [ ] **Step 3: 改造**

`dispatch_agent.py:120`：

```python
# 改前: _MAX_DEPTH = 1
from src.core.config import get_system_config
def _max_depth() -> int:
    return get_system_config().dispatch.max_depth
```

`config/system.yaml`：

```yaml
dispatch:
  max_depth: 5
```

`config.py`：

```python
class DispatchConfig(BaseModel):
    max_depth: int = 5

class SystemConfig(BaseModel):
    dispatch: DispatchConfig = Field(default_factory=DispatchConfig)
```

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && python -m pytest tests/unit/test_dispatch_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/capabilities/tools/dispatch_agent.py config/system.yaml backend/src/core/config.py backend/tests/unit/test_dispatch_agent.py
git commit -m "feat: A10 dispatch_agent max_depth 1→5，可经 system.yaml 调整"
```

---

### Task 12: A10 — PersonaPanel UI 改"历史/归档"语义（R7）

**Files:**
- Modify: `frontend/src/components/PersonaPanel.tsx`（如存在；否则跳过）
- Test: `frontend/src/__tests__/PersonaPanel.test.tsx`

- [ ] **Step 1: 检查文件存在**

Run: `ls frontend/src/components/PersonaPanel.tsx`

如果不存在 → 创建占位 task 笔记，跳过测试与 commit；spec R7 提示存量数据无 UI 暴露。

- [ ] **Step 2: 写失败测试**（如文件存在）

```tsx
test('PersonaPanel shows existing pending proposals as 历史 not 待审批', () => {
  const proposals = [{ id: 'p1', status: 'pending', desc: '...' }]
  render(<PersonaPanel proposals={proposals} />)
  expect(screen.getByText(/历史/)).toBeInTheDocument()
  expect(screen.queryByText(/待审批/)).not.toBeInTheDocument()
})
```

- [ ] **Step 3: 改 label**

把 `pending` 状态的中文从"待审批"改成"历史 / 已归档"，并在 panel 顶部加一行说明：

> A10 之后所有 persona 改动调用即生效，不再走审批流程。下方为历史归档数据。

- [ ] **Step 4: 跑测试 + 视觉检查**

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(ui): A10 后 PersonaPanel pending 数据改为历史归档语义"
```

---

### Task 13: P1 集成测试

**Files:**
- Test: `backend/tests/integration/test_freedom_e2e.py`

- [ ] **Step 1: 端到端测试**

```python
async def test_e2e_agent_creator_grants_full_toolstack():
    """A4 + A7 闭环：agent_creator 能创建带 bash + dispatch_agent 的新 Agent。"""
    cap = CreateAgentConfigCapability()
    result = await cap.execute(
        name="frontend_designer_e2e",
        description="前端设计专家",
        system_prompt="你写前端代码",
        tools=["bash", "write_file", "dispatch_agent", "web_fetch", "web_search", "read_file"],
    )
    assert result["success"]
    assert set(result["agent"]["tools"]) >= {"bash", "write_file", "dispatch_agent"}

async def test_e2e_agent_self_modify_via_update():
    """A10 闭环：任何 Agent 都能调 update_agent_config 给自己加工具。"""
    cap = UpdateAgentConfigCapability()
    result = await cap.execute(
        agent_name="frontend_designer_e2e",
        patch={"tools": ["bash", "write_file", "json_tool"]},
    )
    assert result["success"]

async def test_e2e_dispatch_4_levels_deep():
    """A10 闭环：dispatch_agent 能嵌套到 4 层。"""
    # depth=0 → dispatch (depth=1) → dispatch (depth=2) → dispatch (depth=3) → dispatch (depth=4) — 都允许
    # depth=5 才拒
    pass  # 通过 ContextVar 模拟 depth 测试
```

- [ ] **Step 2-5: 跑测试 / commit**

```bash
git commit -m "test: P1 自由化集成测试 (A4+A10 闭环)"
```

---

# Phase P2 — 全局访问密码 (A11)

### Task 14: A11 — `system.yaml: server.access_password` 配置

**Files:**
- Modify: `config/system.yaml`
- Modify: `backend/src/core/config.py`
- Test: `backend/tests/unit/test_system_config.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_access_password_default_empty():
    cfg = load_system_config()
    assert cfg.server.access_password == ""

def test_access_password_loaded_from_yaml(tmp_path):
    (tmp_path / "system.yaml").write_text("server:\n  access_password: secret123\n")
    cfg = load_system_config(config_dir=tmp_path)
    assert cfg.server.access_password == "secret123"
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 加字段**

`system.yaml`:

```yaml
server:
  # ... existing
  access_password: ""   # 空 = 不开启门禁
  failed_login_lockout_seconds: 60
  failed_login_max_attempts: 5
```

`config.py`:

```python
class ServerConfig(BaseModel):
    # ... existing
    access_password: str = ""
    failed_login_lockout_seconds: int = 60
    failed_login_max_attempts: int = 5
```

- [ ] **Step 4-5: 跑测试 / commit**

```bash
git commit -m "feat(config): A11 server.access_password yaml 字段"
```

---

### Task 15: A11 — 后端 HTTP 鉴权中间件

**Files:**
- Create: `backend/src/api/middleware/auth.py`
- Modify: `backend/src/api/main.py`（注册中间件）
- Test: `backend/tests/integration/test_auth_middleware.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_health_no_auth_required():
    """A11: /api/health 不要求 token（健康检查不能被门挡住）。"""
    res = await client.get("/api/health")
    assert res.status_code == 200

async def test_other_api_requires_token_when_password_set(monkeypatch):
    monkeypatch.setattr("src.core.config.get_system_config", lambda: types.SimpleNamespace(
        server=types.SimpleNamespace(access_password="s3cret", failed_login_max_attempts=5, failed_login_lockout_seconds=60)
    ))
    res = await client.get("/api/agents")
    assert res.status_code == 401
    assert res.json()["error"] == "auth_required"

async def test_correct_token_passes(monkeypatch):
    # 同上 monkeypatch
    res = await client.get("/api/agents", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200

async def test_wrong_token_returns_401(monkeypatch):
    res = await client.get("/api/agents", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401
    assert res.json()["error"] == "auth_invalid"

async def test_lockout_after_5_failures(monkeypatch):
    for _ in range(5):
        await client.get("/api/agents", headers={"Authorization": "Bearer wrong"})
    res = await client.get("/api/agents", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 429  # 锁定
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现中间件**

```python
# backend/src/api/middleware/auth.py
import time
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import get_system_config

EXEMPT_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}

class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._failures: dict[str, list[float]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        cfg = get_system_config().server
        if not cfg.access_password:
            return await call_next(request)
        
        if request.url.path in EXEMPT_PATHS or not request.url.path.startswith("/api/"):
            return await call_next(request)
        
        client_ip = request.client.host if request.client else "unknown"
        if self._is_locked(client_ip, cfg):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "auth_required"}, status_code=401)
        
        token = auth[7:]
        if token != cfg.access_password:
            self._record_failure(client_ip, cfg)
            return JSONResponse({"error": "auth_invalid"}, status_code=401)
        
        return await call_next(request)
    
    def _is_locked(self, ip: str, cfg) -> bool:
        now = time.time()
        cutoff = now - cfg.failed_login_lockout_seconds
        self._failures[ip] = [t for t in self._failures[ip] if t > cutoff]
        return len(self._failures[ip]) >= cfg.failed_login_max_attempts
    
    def _record_failure(self, ip: str, cfg):
        self._failures[ip].append(time.time())
```

`main.py`：

```python
from src.api.middleware.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)
```

- [ ] **Step 4-5: 跑测试 / commit**

```bash
git commit -m "feat(auth): A11 全局密码 HTTP 中间件 + IP 锁定"
```

---

### Task 16: A11 — WebSocket 鉴权（query 参数 + close code 4401）

**Files:**
- Modify: `backend/src/api/websocket/handlers.py`
- Test: `backend/tests/integration/test_ws_auth.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_ws_no_token_closes_4401():
    async with TestClient(app).websocket_connect("/ws") as ws:
        # 应该被 close
        with pytest.raises(WebSocketDisconnect) as exc:
            await ws.receive_json()
        assert exc.value.code == 4401

async def test_ws_correct_token_connects(monkeypatch):
    # monkeypatch password
    async with TestClient(app).websocket_connect("/ws?token=s3cret") as ws:
        await ws.send_json({"event_type": "ping"})
        msg = await ws.receive_json()
        assert msg["event_type"] in ("pong", "connected")
```

- [ ] **Step 2-5: 实现 + 跑通过 + commit**

```python
# handlers.py:websocket_endpoint
async def websocket_endpoint(websocket: WebSocket):
    cfg = get_system_config().server
    if cfg.access_password:
        token = websocket.query_params.get("token", "")
        if token != cfg.access_password:
            await websocket.close(code=4401, reason="auth_invalid")
            return
    await websocket.accept()
    # ... existing
```

```bash
git commit -m "feat(auth): A11 WS 鉴权 query 参数 + close 4401"
```

---

### Task 17: A11 — 前端登录页 + axios/fetch 拦截器 + WS 带 token

**Files:**
- Create: `frontend/src/components/LoginPage.tsx`
- Modify: `frontend/src/api/client.ts`（fetch wrapper 加 Authorization header + 401 拦截）
- Modify: `frontend/src/hooks/useWebSocket.ts`（连接 URL 加 ?token=）
- Modify: `frontend/src/App.tsx`（未登录跳 LoginPage）
- Modify: `frontend/src/store/appStore.tsx`（存 token）
- Test: `frontend/src/__tests__/Auth.test.tsx`

- [ ] **Step 1-5: 标准 5 步 TDD**

LoginPage 表单 → 用户输入密码 → 调 `POST /api/health`（探测 token 是否对）→ 存 localStorage `auth_token` → 跳 / 主页。

`client.ts` 加：

```ts
const TOKEN_KEY = 'auth_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const token = getToken()
  const headers = new Headers(init?.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(url, { ...init, headers })
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY)
    window.location.href = '/login'
  }
  return res
}
```

`useWebSocket.ts`：

```ts
const wsUrl = `${origin}/ws${token ? `?token=${encodeURIComponent(token)}` : ''}`
```

```bash
git commit -m "feat(auth): A11 前端登录页 + token 拦截器 + WS 带 token"
```

---

### Task 18: A11 — nginx 配置示例 + 文档 (R4)

**Files:**
- Modify: `docs/deployment.md`（追加 A11 章节）

- [ ] **Step 1-5: 写文档 / commit**

```markdown
## A11 公网部署密码门禁

启用：

```yaml
# config/system.yaml
server:
  access_password: "<your-secret>"
```

### nginx 反向代理示例

WebSocket query string 含 `token` 参数会被默认 access_log 记录。屏蔽方法：

```nginx
log_format masked '$remote_addr - $remote_user [$time_local] "$request_unmasked" ...';
map $request $request_unmasked {
    ~*token=[^&\s]* "(masked)";
    default $request;
}

server {
    location /ws {
        proxy_pass http://backend:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    access_log /var/log/nginx/access.log masked;
}
```

强烈建议在公网部署时配 HTTPS，避免 token 明文传输。
```

```bash
git commit -m "docs: A11 nginx 配置示例 + 反代日志屏蔽 token"
```

---

### Task 19: A11 集成测试

```bash
git commit -m "test: A11 全局密码 e2e 测试（HTTP + WS + 锁定）"
```

---

# Phase P3 — 附件支持 (B1)

### Task 20: B1 — 数据模型 + 落盘

**Files:**
- Create: `backend/src/core/attachment.py`
- Create: `data/attachments/` 目录（首次启动自动创建）
- Test: `backend/tests/unit/test_attachment.py`

- [ ] **Step 1: 写失败测试**

```python
def test_attachment_create_writes_file_and_meta():
    store = AttachmentStore()
    att = store.create(
        filename="hello.txt",
        mime_type="text/plain",
        content=b"hi there",
        scope="chatroom:r1",
        uploaded_by="user",
    )
    assert att.id
    assert att.size_bytes == 8
    p = Path(att.storage_path)
    assert p.exists() and p.read_bytes() == b"hi there"

def test_attachment_list_by_scope():
    store = AttachmentStore()
    store.create(filename="a.txt", mime_type="text/plain", content=b"a", scope="chat_session:s1", uploaded_by="user")
    store.create(filename="b.txt", mime_type="text/plain", content=b"b", scope="chatroom:r2", uploaded_by="user")
    rows = store.list(scope="chat_session:s1")
    assert len(rows) == 1 and rows[0].filename == "a.txt"

def test_attachment_delete_removes_file():
    store = AttachmentStore()
    att = store.create(filename="x.txt", mime_type="text/plain", content=b"x", scope="chatroom:r3", uploaded_by="user")
    store.delete(att.id)
    assert not Path(att.storage_path).exists()
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

```python
# backend/src/core/attachment.py
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import uuid

@dataclass
class Attachment:
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    created_at: datetime
    uploaded_by: str
    scope: str
    meta: dict

ATTACHMENTS_ROOT = Path("data/attachments")

class AttachmentStore:
    def __init__(self, root: Path = ATTACHMENTS_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "_index.json"
        self.index = self._load_index()
    
    def _load_index(self) -> dict:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {}
    
    def _save_index(self):
        self.index_path.write_text(json.dumps(self.index, default=str, indent=2))
    
    def create(self, *, filename: str, mime_type: str, content: bytes, scope: str, uploaded_by: str, meta: dict = None) -> Attachment:
        att_id = str(uuid.uuid4())
        scope_hash = hashlib.sha1(scope.encode()).hexdigest()[:12]
        scope_dir = self.root / scope_hash
        scope_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in filename if c.isalnum() or c in "._-")[:80]
        path = scope_dir / f"{att_id}__{safe}"
        path.write_bytes(content)
        att = Attachment(
            id=att_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            storage_path=str(path),
            created_at=datetime.utcnow(),
            uploaded_by=uploaded_by,
            scope=scope,
            meta=meta or {},
        )
        self.index[att_id] = asdict(att)
        self._save_index()
        return att
    
    def list(self, *, scope: str = None) -> list[Attachment]:
        rows = self.index.values()
        if scope:
            rows = [r for r in rows if r["scope"] == scope]
        return [Attachment(**{**r, "created_at": datetime.fromisoformat(r["created_at"]) if isinstance(r["created_at"], str) else r["created_at"]}) for r in rows]
    
    def get(self, att_id: str) -> Attachment | None:
        r = self.index.get(att_id)
        if not r:
            return None
        return Attachment(**{**r, "created_at": datetime.fromisoformat(r["created_at"]) if isinstance(r["created_at"], str) else r["created_at"]})
    
    def delete(self, att_id: str) -> bool:
        r = self.index.get(att_id)
        if not r:
            return False
        Path(r["storage_path"]).unlink(missing_ok=True)
        del self.index[att_id]
        self._save_index()
        return True
```

- [ ] **Step 4-5: 跑通过 / commit**

```bash
git commit -m "feat: B1 附件存储 (AttachmentStore + 落盘 + 索引)"
```

---

### Task 21: B1 — 上传 API + multipart

**Files:**
- Create: `backend/src/api/routes/attachments.py`
- Modify: `backend/src/api/routes/__init__.py`（注册）
- Modify: `config/system.yaml`（attachment 配置）
- Test: `backend/tests/integration/test_attachments_api.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_upload_attachment_returns_id(client):
    files = {"file": ("hello.txt", b"hello world", "text/plain")}
    res = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["id"]
    assert data["filename"] == "hello.txt"

async def test_upload_too_large_rejected(client, monkeypatch):
    # 配置上限 1KB
    monkeypatch.setattr(...attachment.max_size_bytes, 1024)
    files = {"file": ("big.bin", b"x" * 2048, "application/octet-stream")}
    res = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    assert res.status_code == 413

async def test_upload_blocked_mime_rejected(client, monkeypatch):
    monkeypatch.setattr(...attachment.allowed_mime_prefixes, ["image/", "text/"])
    files = {"file": ("evil.exe", b"...", "application/x-executable")}
    res = await client.post("/api/attachments?scope=chatroom:r1", files=files)
    assert res.status_code == 415

async def test_download_attachment(client):
    # 先上传，再 GET /api/attachments/{id}
    pass

async def test_list_by_scope(client):
    # 上传 2 条 → GET /api/attachments?scope=... 返回 2 条
    pass

async def test_delete_attachment(client):
    pass
```

- [ ] **Step 2-5: 实现 routes/attachments.py（POST/GET/DELETE/LIST）+ commit**

`config/system.yaml`：

```yaml
attachments:
  max_size_bytes: 52428800   # 50MB
  allowed_mime_prefixes:
    - "image/"
    - "text/"
    - "application/pdf"
    - "application/json"
    - "application/zip"
```

```bash
git commit -m "feat: B1 附件 REST API (upload/download/list/delete + 类型/大小校验)"
```

---

### Task 22: B1 — 消息引用 attachment_ids

**Files:**
- Modify: `backend/src/core/chatroom.py`（ChatroomMessage 加 `attachments: list[str]`）
- Modify: `backend/src/api/routes/chatrooms.py`（POST messages 接受 attachments）
- Modify: `backend/src/api/routes/agents.py`（ChatPanel 路径同样）
- Modify: `backend/src/api/schemas.py`
- Test: `backend/tests/integration/test_message_with_attachment.py`

- [ ] **Step 1-5: 标准 TDD + commit**

```bash
git commit -m "feat: B1 消息引用 attachment_ids (chatroom + chatpanel)"
```

---

### Task 23: B1 — 前端 paste / 拖拽 / 多文件上传 UI

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`
- Modify: `frontend/src/components/ChatroomPanel.tsx`
- Modify: 各自 .css
- Modify: `frontend/src/api/client.ts`（uploadAttachment helper）
- Test: `frontend/src/__tests__/AttachmentInput.test.tsx`

- [ ] **Step 1-5:**

加 paste 监听：

```tsx
const composerRef = useRef<HTMLDivElement>(null)
useEffect(() => {
  const el = composerRef.current
  if (!el) return
  function onPaste(e: ClipboardEvent) {
    const items = Array.from(e.clipboardData?.items || [])
    const files = items.filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean) as File[]
    if (files.length) {
      e.preventDefault()
      handleUpload(files)
    }
  }
  el.addEventListener('paste', onPaste)
  return () => el.removeEventListener('paste', onPaste)
}, [])
```

加拖拽：onDragOver / onDrop。
加文件按钮 📎 input[type=file] hidden。
缩略图：图片 thumb，其他用图标。
进度条：fetch 没有 progress，先用 indeterminate spinner。

```bash
git commit -m "feat(ui): B1 ChatPanel/ChatroomPanel 支持 paste/拖拽/选择文件上传"
```

---

### Task 24: B1 — 工作区符号链接 + Windows fallback (R6)

**Files:**
- Create: `backend/src/core/attachment_workspace.py`
- Test: `backend/tests/unit/test_attachment_workspace.py`

- [ ] **Step 1-5:**

```python
def link_attachment_to_workspace(att: Attachment, workspace_root: Path) -> Path:
    """让 Agent 用 read_file 能在工作区读到附件。
    Linux: symlink
    Windows: 文件复制
    """
    target_dir = workspace_root / ".attachments" / att.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / att.filename
    src = Path(att.storage_path)
    if target.exists():
        return target
    try:
        target.symlink_to(src.absolute())
    except (OSError, NotImplementedError):
        # Windows or permissions issue → copy
        import shutil
        shutil.copy2(src, target)
    return target
```

```bash
git commit -m "feat: B1 附件挂入工作区 (symlink + Windows copy fallback)"
```

---

### Task 25: B1 — Agent 消费 — 文本/PDF 路径塞 system prompt

**Files:**
- Modify: `backend/src/core/chatroom_orchestrator.py`（拼 payload 时把附件路径加进上下文）
- Modify: `backend/src/api/routes/agents.py`（ChatPanel 同步）
- Test: `backend/tests/integration/test_attachment_agent_consume.py`

- [ ] **Step 1-5:** 略，标准 TDD

把附件元数据 + 路径塞进 system reminder 块（A16 形式）：

```
<attached_files>
  <file id="att_xxx" path="/workspace/.attachments/att_xxx/hello.txt" mime="text/plain" size="123">hello.txt</file>
</attached_files>
```

Agent 用 `read_file` 工具自己读。

```bash
git commit -m "feat: B1 Agent 消费 — 文本/PDF 通过工作区路径，Agent 自助 read_file"
```

---

### Task 26: B1 — Agent 消费 — 图片走 vision payload

**Files:**
- Modify: `backend/src/core/llm/openai_client.py`（添加 image_url 类型支持）
- Modify: `backend/src/core/llm/anthropic_client.py`（image type）
- Test: `backend/tests/unit/test_llm_vision_payload.py`

- [ ] **Step 1-5:**

OpenAI vision：

```python
{"role": "user", "content": [
    {"type": "text", "text": "用户问：..."},
    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64_content}"}},
]}
```

Anthropic vision：

```python
{"role": "user", "content": [
    {"type": "text", "text": "..."},
    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64_content}},
]}
```

`chatroom_orchestrator` 把 message.attachments 中 image/* 的附件 inline 进 vision payload；非图片的走 Task 25 路径。

```bash
git commit -m "feat: B1 Agent 消费 — 图片 inline base64 走 OpenAI/Anthropic vision"
```

---

### Task 27: B1 — 前端展示已附件消息

**Files:**
- Modify: `ChatroomPanel.tsx` / `ChatPanel.tsx`（消息渲染时显示附件缩略图/图标）

- [ ] **Step 1-5:**

```tsx
{message.attachments?.map(attId => (
  <AttachmentChip key={attId} id={attId} />
))}
```

`AttachmentChip` 组件：图片走 `<img src="/api/attachments/{id}">`，其他走 📎 + filename + 点击下载。

```bash
git commit -m "feat(ui): B1 消息卡片展示附件缩略图/链接"
```

---

### Task 28: B1 — 集成测试

```bash
git commit -m "test: B1 附件 e2e (上传 + 消息引用 + Agent 看到 + 删除)"
```

---

### Task 29 (可选): B1 — 附件 cleanup 任务

定时任务：删除 90 天以前的孤儿附件（不被任何消息引用的）。spec 列为 Phase 2，**本 plan 不实施**，仅留 task 占位说明。

---

# 末尾收尾

### Task 30: 文档同步

**Files:**
- Modify: `agentic-system/CLAUDE.md`（更新 §3.7 能力 / §5.1 API 表格 / §10 设计决策）
- Modify: `docs/api.md`（如存在）

- [ ] **Step 1-5:**

CLAUDE.md 加：
- A4：HIGH_RISK_TOOLS 默认放开 + agent_creation.forbidden_tools 配置
- A8：AgentPanel 重新装载按钮
- A10：propose-approve-apply 三段式已删除；新动作动词列表
- A11：可选 server.access_password
- B1：附件 API 表

```bash
git commit -m "docs: 更新 CLAUDE.md 反映 P0-P3 改动"
```

---

### Task 31: 全套 P0-P3 集成测试

```bash
cd backend && python -m pytest tests/ -v
cd frontend && npx vitest run
```

确认全部通过；如有遗留失败按 spec §11 补测。

```bash
git commit -m "test: P0-P3 整合测试通过"
```

---

## 实施顺序与依赖

```
P0 — Task 1, 2, 3 (并行)      ← 纯前端，最快出成绩
P1 — Task 4 → Task 5,6,7 (A4) || Task 8,9,10,11,12 (A10) → Task 13 (集成)
P2 — Task 14 → Task 15 → Task 16 → Task 17 → Task 18 → Task 19
P3 — Task 20 → Task 21 → Task 22 → Task 23 || Task 24 → Task 25,26 → Task 27 → Task 28
末 — Task 30 → Task 31
```

每完成 Phase 一次，跑完整测试套件，再开下一个。

---

**计划完毕。**
