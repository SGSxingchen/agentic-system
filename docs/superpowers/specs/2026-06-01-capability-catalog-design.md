# 能力库:Tools / Skills / MCP 三层目录 + 一键装配

**日期**: 2026-06-01
**作者**: 项目维护者
**状态**: 设计待评审

> 把「能力与扩展」从零散的 per-agent 配置，升级成**仓库级能力库（catalog）+ 一键装配到 agent** 的统一形态。
> Tools / Skills / MCP 三者在前端平级展示、可浏览、可装配。

---

## 1. 背景与动机

当前三类能力的状态不一致：

| 能力 | 仓库级预设 | 前端独立面板 | 问题 |
|------|-----------|------------|------|
| **Tools** | ✅ `config/capabilities.yaml`（23+ 个） | ❌ 只埋在 AgentPanel 勾选框 | 用户看不到完整工具目录 |
| **Skills** | ❌ 无 `skills/` 目录、零预设 | ✅ SkillsPanel（但空） | 面板空白，没有「库」概念 |
| **MCP** | ❌ 仅 per-agent，零预设 | ✅ McpPanel（但空） | 面板空白，没有「库」概念 |

用户诉求：**像 Tools 那样在仓库里预置几个 Skills 和 MCP**，并让 **Tools 也升为与 Skills/MCP 平级的面板**，三者都能浏览 + 装配。

## 2. 目标 / 非目标

**目标**
- 仓库内置一批可直接展示的 Skills 与 MCP 预设。
- 新增统一的 catalog 读取 + 装配 API，三类能力共用同一交互模型。
- 前端「能力与扩展」下三个平级面板（Tools / Skills / MCP），均支持「浏览库 + 装配到 agent」。

**非目标**
- 不实现 MCP 运行时真实拉起（仍由现有 `mcp_adapter` 负责；预设以模板形态入库，`enabled: false`）。
- 不改动 agent 的工具执行循环、token 预算等运行时逻辑。
- 不做能力的「评分/打分」系统（“评级”理解为**平级展示**，非数值评分）。
- 不引入新的鉴权层；装配复用现有 agent 配置更新 + 热重载链路。

## 3. 现状关键事实（代码审计）

- **Skills**：`core/skills.py` 的 `load_agent_skills()` 支持两种来源——扫描 `directories` 下的 `SKILL.md`，或读 agent 配置内联 `items`（可带 `path` 或内联 `name/description/instructions`）。`SkillMetadata`(frozen dataclass) 字段：`name / description / instructions / source / enabled / extra`。SKILL.md 用 YAML frontmatter（`name`、`description` 必填）+ markdown 正文。Skills 仅作**参考指导**，不授予新工具权限。
- **MCP**：`core/mcp.py` 的 `MCPServerConfig`(frozen) 字段：`name / command / args / env / enabled / cwd / description / transport / url`。已有 `validate_mcp_server_payload` / `sanitize_mcp_servers_for_response`（env 脱敏）/ `merge_mcp_servers_preserving_masked_env`。当前仅 per-agent 配置，无仓库级目录。
- **Tools**：`config/capabilities.yaml` 定义 native/dynamic 能力；`GET /api/agents/capabilities/list`（`routes/agents.py`）返回 `[{name, description, parameters}]`，前端 `api.listCapabilities()` 缓存 60s。装配通过 `PUT /api/agents/{name}`（更新 `tools`）。
- **前端**：`Sidebar.tsx`「能力与扩展」段已有 `skills`→`SkillsPanel`、`mcp`→`McpPanel`，无 `tools` 项。`App.tsx` 的 `renderPanel()` switch 按 panel key 映射组件。两个面板均 `api.listAgents()` 后按 agent 聚合展示。
- **装配现链路**：`update_agent_config`（`agent_management.py`）落盘 `config/agents.yaml` 并热重载；`PUT /api/agents/{name}` 同样走配置更新 + reload。

## 4. 架构总览

```
                       ┌─────────────────────────────────────────┐
  前端「能力与扩展」    │  ToolsPanel    SkillsPanel    McpPanel    │
  （三个平级面板）      │     │             │             │        │
                       │     └──── 共用 <CatalogList> ───┘        │
                       └─────────────────┬───────────────────────┘
                                         │ HTTP
                       ┌─────────────────▼───────────────────────┐
   后端 catalog 路由    │  GET  /api/catalog/{tools|skills|mcp}    │
   routes/catalog.py    │  POST /api/catalog/{kind}/{name}/assemble│
                       └───┬───────────────┬──────────────┬───────┘
                           │               │              │
              ┌────────────▼──┐  ┌─────────▼────────┐  ┌──▼────────────────┐
   数据来源    │ capabilities  │  │ skills/<slug>/   │  │ config/           │
              │ registry(已有)│  │   SKILL.md (新)  │  │ mcp_servers.yaml(新)│
              └───────────────┘  └──────────────────┘  └───────────────────┘
                           │  装配统一写回 ▼
                       config/agents.yaml + 热重载（复用现有链路）
```

## 5. 后端设计

### 5.1 新路由 `backend/src/api/routes/catalog.py`

统一三类能力的「列目录 / 装配」。挂载前缀 `/api/catalog`。

#### `GET /api/catalog/tools`
- 复用 capability registry（`get_capability_registry()`）列出全部能力。
- 每项附 `used_by: [agent_name]`——遍历已注册 agents 的 `tools` 求交集。
- 返回：`[{ name, description, parameters, kind: "tool", used_by: [...] }]`

#### `GET /api/catalog/skills`
- 扫描仓库根 `skills/` 目录，对每个 `<slug>/SKILL.md` 调用 `core/skills.py` 的解析函数得到 `SkillMetadata`。
- 每项附 `used_by`——遍历 agents 的 `skills.items`/`directories`，匹配同名/同 path 的 skill。
- 返回：`[{ name, description, source, instructions_preview, kind: "skill", used_by: [...] }]`（`instructions_preview` 截断 ~400 字，避免大块正文）。

#### `GET /api/catalog/mcp`
- 读 `config/mcp_servers.yaml` 的模板列表，经 `sanitize_mcp_servers_for_response`（env 脱敏）。
- 每项附 `used_by`——匹配 agents 的 `mcp_servers[].name`。
- 返回：`[{ name, command, args, transport, description, enabled, env(masked), kind: "mcp", used_by: [...] }]`

#### `POST /api/catalog/{kind}/{name}/assemble`
- Body：`{ agent_name: str, env?: object }`（`env` 仅 MCP 用，填模板占位）。
- 行为：把目录项「加入」目标 agent 的对应配置字段，复用现有更新链路：
  - `tools` → 把 `name` 加进该 agent `tools` 列表（去重）。
  - `skills` → 把 `{ path: "skills/<slug>/SKILL.md" }` 加进该 agent `skills.items`，并确保 `skills.enabled: true`。
  - `mcp` → 把模板 server 复制进该 agent `mcp_servers`（`enabled: true`，合并 `env`），复用 `validate_mcp_server_payload` + `merge_mcp_servers_preserving_masked_env`。
- 落盘 `config/agents.yaml` + 热重载（与 `update_agent_config` 同一函数路径，不新造写盘逻辑）。
- 返回：更新后的该 agent 配置视图（复用 `_build_agent_info`）。
- 错误：agent 不存在 / 能力名不存在 / MCP 校验失败 → 4xx + 明确 message。

### 5.2 新文件 `config/mcp_servers.yaml`（MCP 模板库）

四个官方 server，均 `enabled: false` 作为模板：

```yaml
mcp_servers:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "<ABS_PATH>"]
    transport: stdio
    enabled: false
    description: 官方文件系统 MCP server；把 <ABS_PATH> 换成允许访问的目录后启用。
  - name: git
    command: npx
    args: ["-y", "@modelcontextprotocol/server-git", "--repository", "<REPO_PATH>"]
    transport: stdio
    enabled: false
    description: 官方 Git MCP server；提供仓库读取/历史查询。
  - name: fetch
    command: npx
    args: ["-y", "@modelcontextprotocol/server-fetch"]
    transport: stdio
    enabled: false
    description: 官方抓取 MCP server；按 URL 拉取网页并转 markdown。
  - name: sqlite
    command: npx
    args: ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "<DB_PATH>"]
    transport: stdio
    enabled: false
    description: 官方 SQLite MCP server；只读/查询本地 sqlite 库。
```

> 加载：在 `main.py` lifespan 或 catalog 路由内惰性读取；缺失文件时回退空列表（沿用 fallback 原则）。

### 5.3 新目录 `skills/`（Skills 库）

结构忠于官方：`skills/<slug>/SKILL.md`（frontmatter `name`/`description` + 正文）。

预置清单（**spec 评审时最终确认**，默认提案）：

| slug | 来源 | 许可 | 处理 |
|------|------|------|------|
| `pdf` | anthropics/skills | source-available（非开源） | 拉 SKILL.md，保留 attribution |
| `docx` | anthropics/skills | source-available（非开源） | 拉 SKILL.md，保留 attribution |
| `mcp-builder` | anthropics/skills（Apache-2.0 类） | Apache-2.0 | 直接拉 |
| `webapp-testing` | anthropics/skills（Apache-2.0 类） | Apache-2.0 | 直接拉 |

- 新增仓库根 `THIRD_PARTY_NOTICES.md`（或在 `skills/NOTICE.md`）记录来源与许可，source-available 技能注明非开源、仅作演示预设。
- 若评审时倾向只用 Apache-2.0，则替换掉 pdf/docx。

> 选 SKILL.md 文件而非 `config/skills.yaml`：忠于官方格式、现有 `directories` 加载器零改即可用、便于后续直接 `git` 增删技能。

## 6. 前端设计

### 6.1 Sidebar 与路由
- `Sidebar.tsx`「能力与扩展」段新增 `tools` 项（置于 `skills` 之上）。
- `App.tsx` `renderPanel()` 新增 `tools` → `<ToolsPanel/>` 分支。
- 类型：`types/index.ts` 的 panel key 联合类型加 `'tools'`。

### 6.2 共用组件 `components/CatalogList.tsx`
- Props：`items`（统一形状 `{name, description, kind, used_by, detail?}`）、`agents`（可装配目标）、`onAssemble(name, agentName, env?)`。
- 每行：名称 + 描述 + `kind` 徽标 + `used_by` chips + 「装配到 ▾agent」下拉 + 按钮；MCP 行额外可展开 env 占位填写。
- 加载/错误/空态统一处理。

### 6.3 三个面板
- **ToolsPanel.tsx**（新）：`GET /api/catalog/tools` → `CatalogList`；点开某项可看 `parameters` JSON Schema。
- **SkillsPanel.tsx**（改）：保留现有「按 agent 聚合」视图，**顶部新增「能力库」段** = `GET /api/catalog/skills` → `CatalogList`。
- **McpPanel.tsx**（改）：同上，顶部加「能力库」段 = `GET /api/catalog/mcp` → `CatalogList`，复用现有 import 逻辑不动。

### 6.4 API client（`api/client.ts`）
- 新增 `listCatalog(kind)` → `GET /api/catalog/{kind}`。
- 新增 `assembleCapability(kind, name, agentName, env?)` → `POST /api/catalog/{kind}/{name}/assemble`。
- 装配成功后刷新对应面板 + 失效 `listCapabilities`/`listAgents` 缓存。

## 7. 数据流：装配一个 skill

1. 用户在 SkillsPanel「能力库」段，对 `pdf` 选择目标 agent `assistant` → 点「装配」。
2. 前端 `POST /api/catalog/skills/pdf/assemble { agent_name: "assistant" }`。
3. 后端把 `{ path: "skills/pdf/SKILL.md" }` 并入 assistant 的 `skills.items`，`skills.enabled=true`，落盘 `config/agents.yaml` + 热重载。
4. 返回更新后的 assistant 配置；前端刷新，`pdf` 的 `used_by` 出现 `assistant`。
5. AgentPanel 查看 assistant 时，skills 挂载里能看到 `pdf`。

## 8. 错误处理

- catalog 读取：文件/目录缺失 → 返回空列表 + 不报 500（fallback）。
- 装配：目标 agent 不存在 → 404；能力名不在库 → 404；MCP env/字段非法 → 422 带字段级 message；受保护字段不受影响（复用现有校验）。
- 前端：装配失败 toast/inline error，不静默吞错。

## 9. 测试计划

**后端（pytest）**
- `GET /api/catalog/tools|skills|mcp` 各返回非空且结构正确；`used_by` 正确反映 agents.yaml。
- skills 目录解析：放一个临时 `SKILL.md` → 出现在 catalog。
- mcp 模板加载：`mcp_servers.yaml` 四项均出现且 env 脱敏。
- 装配 round-trip：assemble skill/tool/mcp 后，目标 agent 配置含新增项且热重载成功；重复装配幂等（去重）。
- 错误：未知 agent / 未知能力 / 非法 MCP env → 对应 4xx。

**前端（.mjs，沿用现有风格）**
- `CatalogList` 渲染 items + `used_by` chips；点击装配触发 `onAssemble` 带正确参数。
- panel 加载 catalog 调用正确端点。

**端到端手测**
- 启动后三面板非空；把 `pdf` 装到 assistant，AgentPanel 可见；把 `filesystem` MCP 装到某 agent，McpPanel `used_by` 更新。

## 10. 影响面 / 兼容性

- 纯增量：新增路由文件、两个配置/目录、一个前端组件 + 一个面板，改 3 处（Sidebar / App.renderPanel / 两个既有面板加「库」段）。
- 不动 agent 运行时、bus、记忆、chatroom。
- `config/agents.yaml` 经装配会增长，但字段语义不变；现有加载器兼容。
- 文档：实现后更新 `agentic-system/CLAUDE.md` §3.7（能力系统）+ §5 API 列表 + §6 前端面板表 + §2 目录结构。

## 11. 评审确认点（已按默认锁定 2026-06-01）

1. **Skills 预置清单** ✅ 按默认：pdf + docx（source-available，带 NOTICE）+ 两个 Apache-2.0 工程类技能（按 anthropics/skills 实际存在的为准）。
2. **装配二次确认** ✅ 按默认：点一下即落盘热重载，不加确认弹窗。
3. **MCP env 占位** ✅ 按默认：允许先装上、之后再补路径/key 才 `enable`，不强制填写。
