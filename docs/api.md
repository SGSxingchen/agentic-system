# API 文档

> 最后更新: 2026-05-05 | 基于 backend/src/api/routes/ 实际代码

## 基础信息

- **基础 URL**: `http://localhost:8001`
- **WebSocket**: `ws://localhost:8001/ws`
- **数据格式**: JSON
- **Swagger UI**: `http://localhost:8001/docs`

## 统一响应格式

所有 REST API 使用统一响应格式:

```json
{
  "status": "ok",          // "ok" 或 "error"
  "message": "...",        // 可选的消息
  "data": { ... }          // 实际数据
}
```

---

## 健康检查

### GET /api/health

返回系统各组件运行状态。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "status": "ok",
    "bus_running": true,
    "agent_loaded": true,
    "memory_initialized": true,
    "agents_registered": 4,
    "version": "0.3.0",
    "uptime": 123,
    "agents": {
      "assistant": "idle"
    }
  }
}
```

---

## 配置管理

### GET /api/config

获取当前配置 (隐藏 API Key)。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "llm": {
      "provider": "openai",
      "model": "gpt-4",
      "api_key_set": true,
      "base_url": "",
      "temperature": 0.7,
      "max_tokens": 4096
    },
    "tools": {
      "web_search": {
        "provider": "duckduckgo",
        "base_url": "",
        "api_key_set": false,
        "max_results": 5,
        "timeout": 10
      },
      "web_fetch": {
        "timeout": 10,
        "max_chars": 4000
      },
      "file": {
        "workspace_root": "./workspace"
      },
      "shell": {
        "enabled": false,
        "timeout": 30
      },
      "custom": {
        "notion_search": {
          "enabled": true,
          "base_url": "https://api.notion.com",
          "api_key_set": true,
          "extra": {
            "version": "2022-06-28"
          }
        }
      }
    }
  }
}
```

### POST /api/config

更新 LLM 配置并热重载 Agent。

**请求体:**
```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4",
    "api_key": "sk-xxx",
    "base_url": "",
    "temperature": 0.7,
    "max_tokens": 4096
  },
  "tools": {
    "web_search": {
      "provider": "duckduckgo",
      "base_url": "",
      "api_key": "",
      "max_results": 5,
      "timeout": 10
    },
    "web_fetch": {
      "timeout": 10,
      "max_chars": 4000
    },
    "file": {
      "workspace_root": "./workspace"
    },
    "shell": {
      "enabled": false,
      "timeout": 30
    },
    "custom": {}
  }
}
```

`api_key` 留空、传 `null` 或传入 `********` / `••••••••` 这类遮罩值时，后端会保留已有密钥；响应中只返回 `api_key_set`，不会明文返回 Key。
OpenAI 兼容服务的 `base_url` 可填写服务根地址或 `/v1` 地址，保存时会规范化为 API 根路径；填写空字符串表示清空自定义地址并使用 SDK 默认端点。

**响应:**
```json
{
  "status": "ok",
  "message": "配置已更新并重新加载"
}
```

### POST /api/config/models

从当前 provider 拉取可用模型列表，供设置页刷新模型下拉框。

**请求体:**
```json
{
  "provider": "openai",
  "base_url": "https://proxy.example.com",
  "api_key": ""
}
```

所有字段均可选；空 `api_key` 或遮罩值会沿用服务器已保存的密钥。OpenAI 兼容 `base_url` 会自动规范化到 `/v1` API 根路径；远端失败时返回 `status: "error"` 与可读 `message`，同时 `data.models` 为空，前端可降级到内置短表。

---

## 智能体管理

### GET /api/agents

列出所有已注册智能体。

**响应:**
```json
{
  "status": "ok",
  "data": [
    {
      "name": "assistant",
      "status": "idle",
      "capabilities": ["chat", "conversation"],
      "description": "对话助手智能体"
    },
    {
      "name": "planner",
      "status": "idle",
      "capabilities": ["task_decomposition", "planning"],
      "description": "任务规划智能体"
    }
  ]
}
```

### GET /api/agents/{name}

获取特定智能体详情。

**路径参数:** `name` — 智能体名称 (assistant / planner / coder / reviewer)

**响应:**
```json
{
  "status": "ok",
  "data": {
    "name": "assistant",
    "status": "idle",
    "capabilities": ["chat", "conversation"],
    "description": "对话助手智能体"
  }
}
```


### GET /api/agents/persona-bindings

获取 Agent 默认人格、Session 人格绑定、绑定优先级和建议展示角色。新前端应从智能体页面调用该接口；旧 `/api/personas/bindings` 保留兼容。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "agents": {"assistant": "base-assistant"},
    "sessions": {"session-1": "base-assistant"},
    "precedence": ["request_persona_id", "session_binding", "agent_binding", "base_persona"],
    "base_persona_id": "base-assistant",
    "roles": ["assistant", "tool_creator", "agent_creator", "planner", "coder", "reviewer"]
  }
}
```

### PUT /api/agents/persona-bindings/agents/{agent_name}

设置 Agent 角色默认人格。生效顺序仍低于请求指定人格和会话绑定。

**请求体:**
```json
{ "persona_id": "base-assistant" }
```

### DELETE /api/agents/persona-bindings/agents/{agent_name}

解绑 Agent 角色默认人格；后续解析将回退到基础人格。

### PUT /api/agents/persona-bindings/sessions/{session_id}

设置某个会话的人格绑定。生效顺序低于请求体显式 `persona_id`，高于 Agent 默认人格。

**请求体:**
```json
{ "persona_id": "base-assistant" }
```

### DELETE /api/agents/persona-bindings/sessions/{session_id}

解绑指定会话的人格绑定；后续解析将继续按 Agent 默认人格和基础人格回退。

### POST /api/agents/{name}/invoke

直接调用某个智能体。

**路径参数:** `name` — 智能体名称

**请求体:**
```json
{
  "data": {
    "message": "你好"
  }
}
```

兼容说明：旧前端曾直接提交 `{"input": "你好"}` 这类扁平 payload；
后端会自动包装为 `data`，避免校验通过但实际空输入调用 Agent。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "response": "你好！我是 AI 助手。",
    "original_message": "你好",
    "memories_used": 2
  }
}
```

---

## 任务管理

### POST /api/tasks

提交新任务，按指定 Pipeline 模板异步执行。

**请求体:**
```json
{
  "requirement": "实现一个用户登录功能",
  "pipeline": "code_generation_and_review"
}
```

**响应:**
```json
{
  "status": "ok",
  "message": "任务已提交",
  "data": {
    "task_id": "uuid-xxx",
    "status": "planning"
  }
}
```

### GET /api/tasks

列出所有任务。

**响应:**
```json
{
  "status": "ok",
  "data": [
    {
      "task_id": "uuid-xxx",
      "status": "planning",
      "requirement": "实现一个用户登录功能",
      "created_at": "2026-03-25T10:00:00",
      "updated_at": "2026-03-25T10:01:00"
    }
  ]
}
```

### GET /api/tasks/{task_id}

获取任务详情 (包含 plan/code/review 结果)。

**路径参数:** `task_id` — 任务 UUID

### DELETE /api/tasks/{task_id}

取消/删除任务。

---

## Pipeline

### GET /api/pipelines/templates

获取预定义 Pipeline 模板。

**响应:**
```json
{
  "status": "ok",
  "data": [
    {
      "name": "code_generation_and_review",
      "description": "代码生成与审查流水线",
      "mode": "sequential",
      "steps": [
        {
          "name": "plan",
          "agent": "planner",
          "capability": "planner",
          "output_key": "plan"
        }
      ]
    },
    {
      "name": "full_pipeline",
      "description": "完整开发流水线：规划 → 编码 → 审查 → 修复",
      "mode": "sequential",
      "steps": []
    }
  ]
}
```

### POST /api/pipelines/execute

执行 Pipeline。

**请求体:**
```json
{
  "requirement": "实现排序算法",
  "template_name": "code_generation_and_review",
  "options": {}
}
```

说明:
- `template_name` 优先级高于 `pipeline_type`
- `input` 是 `requirement` 的别名
- 执行器会把 `requirement` 同时注入为 `user_requirement` / `requirement` / `message`
- 若模板步骤声明 `timeout`，超时会在对应 `step_results` 中返回失败信息

Pipeline CRUD 中单个步骤支持以下字段:
- `name`
- `agent`
- `input`
- `output_key`
- `condition`
- `max_iterations`
- `timeout`

**响应:**
```json
{
  "status": "ok",
  "message": "管线 'code_generation_and_review' 执行完成",
  "data": {
    "status": "completed",
    "context": {
      "user_requirement": "实现排序算法"
    },
    "step_results": [
      {
        "step_name": "plan",
        "status": "completed",
        "output": {},
        "error": null,
        "duration_ms": 12.5
      }
    ],
    "duration_ms": 35.1
  }
}
```

### POST /api/pipelines

创建新的 Pipeline 模板，写入 `config/pipelines.yaml`。

**请求体:**
```json
{
  "name": "quick_plan",
  "description": "只做需求规划",
  "mode": "sequential",
  "steps": [
    {
      "name": "plan",
      "agent": "planner",
      "input": {
        "requirement": "${user_requirement}"
      },
      "output_key": "plan",
      "max_iterations": 1
    }
  ]
}
```

### PUT /api/pipelines/{name}

更新已有 Pipeline 模板。请求体字段均可选：`description`、`mode`、`steps`。

### DELETE /api/pipelines/{name}

删除已有 Pipeline 模板。

---

## 记忆系统

### GET /api/memory/stats

获取记忆统计。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "total": 42,
    "by_type": {
      "episodic": 20,
      "semantic": 15,
      "procedural": 7
    }
  }
}
```

### GET /api/memory/list

列出记忆。

**查询参数:**
- `type` (可选) — 记忆类型 (episodic / semantic / procedural)
- `limit` (可选) — 返回数量，默认 20

### POST /api/memory/search

搜索记忆。

**请求体:**
```json
{
  "query": "用户偏好",
  "max_results": 5
}
```

### POST /api/memory/create

手动创建记忆。

**请求体:**
```json
{
  "content": "用户偏好使用 Python",
  "type": "semantic",
  "importance": 0.8,
  "metadata": {}
}
```

### PUT /api/memory/{memory_id}

更新指定记忆内容、类型、重要性或元数据。

**请求体（均可选）:**
```json
{
  "content": "更新后的记忆内容",
  "type": "semantic",
  "importance": 0.75,
  "metadata": {"memory_kind": "preference"}
}
```

### DELETE /api/memory/{memory_id}

删除指定记忆。

### GET /api/memory/settings

获取记忆系统配置和当前运行后端状态（不包含敏感信息）。

### POST /api/memory/settings

保存记忆系统设置。反思阈值、召回参数、巩固/遗忘阈值会在当前进程内即时生效；后端类型、持久化目录、collection 等存储相关配置写入运行时配置，通常需重启服务后完全切换。

**请求体（均可选）:**
```json
{
  "auto_reflection_enabled": true,
  "reflection_min_turns": 3,
  "reflection_max_messages": 12,
  "recall_max_results": 3,
  "recall_score_threshold": 0.0,
  "backend": "chroma",
  "persist_dir": "./data/chroma"
}
```

### POST /api/memory/consolidate

触发记忆巩固 (去重合并)。

### POST /api/memory/forget

触发记忆遗忘 (基于时间衰减)。

---

## 进化中心

### GET /api/evolution/graph

获取当前 Agent-Tool 能力网络，用于展示主 Agent、子 Agent、工具以及调用关系。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "summary": {
      "agents": 4,
      "tools": 8,
      "dynamic_tools": 1,
      "edges": 12,
      "master_agent": "assistant"
    },
    "nodes": [
      {
        "id": "assistant",
        "type": "agent",
        "capabilities": ["memory_search", "planner", "coder"]
      },
      {
        "id": "requirement_checklist",
        "type": "dynamic_tool",
        "mode": "checklist"
      }
    ],
    "edges": [
      {
        "source": "assistant",
        "target": "planner",
        "kind": "delegates"
      }
    ],
    "supported_dynamic_modes": ["checklist", "regex_extract", "template"]
  }
}
```

### GET /api/evolution/system-status

获取当前 Agentic System Architecture / System State 聚合状态。该接口复用运行时 registry、memory store、pipeline、bus 和配置文件状态，用于进化页展示系统级架构，而不是把 assistant 或 tool 管理误认为进化本身。

**响应片段:**
```json
{
  "status": "ok",
  "data": {
    "overview": {
      "system_name": "Multi-Agent Code System",
      "readiness": "ready",
      "agent_count": 6,
      "tool_count": 14,
      "pipeline_count": 3,
      "model": "openai / gpt-3.5-turbo"
    },
    "components": [
      {
        "id": "agents",
        "title": "Assistants / Agents",
        "status": "healthy",
        "summary": "assistant 是协作入口之一；planner/coder/reviewer/creator 等 Agent 共同构成运行时。",
        "metrics": { "total": 6, "idle": 6 },
        "items": []
      }
    ],
    "graph": { "summary": { "agents": 6, "tools": 14 } }
  }
}
```

### POST /api/evolution/command

根据用户输入的进化目标和当前系统状态生成一条可提交给 Agentic Pipeline 的明确进化指令。生成结果会强调“先审查架构状态，再设计最小可行改造，最后测试验证”，避免把新增 Agent/Tool CRUD 当成进化本身。

**请求体:**
```json
{
  "goal": "增强长期记忆召回解释，并在前端展示可观测状态"
}
```

**响应片段:**
```json
{
  "status": "ok",
  "data": {
    "goal": "增强长期记忆召回解释，并在前端展示可观测状态",
    "target_components": ["memory", "observability"],
    "command": "请作为 Agentic System Evolution 任务执行...",
    "status_snapshot": { "readiness": "ready" }
  }
}
```

### POST /api/evolution/dynamic-tools

运行时创建安全动态工具，并可立即挂载到指定 Agent。

**请求体:**
```json
{
  "name": "requirement_guard",
  "description": "检查需求描述是否包含关键要素",
  "mode": "checklist",
  "config": {
    "required_terms": ["目标", "输入", "输出", "验收"],
    "forbidden_terms": ["随便", "都行"]
  },
  "attach_to_agents": ["assistant"],
  "overwrite": false
}
```

**动态工具模式:**
- `template` — 根据 `config.template` 渲染 `{{text}}` 等占位符
- `checklist` — 根据 `required_terms` / `forbidden_terms` 返回完整性评分
- `regex_extract` — 根据 `config.patterns` 从文本中抽取结构化信息

### POST /api/evolution/reload

从 YAML 重新装载动态工具，并刷新 Agent 的工具绑定。

### GET /api/evolution/tool-prompts

获取所有非 Agent Tool 的提示词配置。`prompt` 可编辑，`schema` 是只读 JSON Schema，用于展示工具入参协议。

**响应:**
```json
{
  "status": "ok",
  "data": [
    {
      "name": "calculator",
      "type": "tool",
      "prompt": "安全数学计算工具",
      "prompt_source": "default",
      "schema": {
        "type": "object",
        "properties": {
          "expression": {
            "type": "string"
          }
        },
        "required": ["expression"]
      }
    }
  ]
}
```

### PUT /api/evolution/tool-prompts/{name}

更新 Tool 暴露给 LLM 的提示词。该接口只写入 `prompt` 字段，不允许修改 JSON Schema。

**请求体:**
```json
{
  "prompt": "用于精确计算数学表达式的工具。适合四则运算、幂运算和常见数学函数。"
}
```

---

## WebSocket

### 连接

```
ws://localhost:8001/ws
```

### 接收事件格式

```json
{
  "event_type": "assistant_response",
  "data": {
    "response": "AI 的回复内容",
    "memories_used": 2
  },
  "timestamp": "2026-03-25T10:00:00"
}
```

### 发送消息格式

```json
{
  "type": "user_message",
  "data": {
    "message": "你好"
  }
}
```

### 事件类型

| 事件 | 方向 | 说明 |
|------|------|------|
| `assistant_response` | 服务端→客户端 | AI 回复 |
| `agent_status_update` | 服务端→客户端 | Agent 状态变化 |
| `user_message` | 客户端→服务端 | 用户消息 |

## 人格系统 API（v2.2）

人格数据持久化在项目本地 `data/personas.json`（可用 `PERSONA_STORE_FILE` 覆盖），默认自动提供 `base-assistant`，未选择人格时向后兼容。

### 人格 CRUD

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/personas?include_archived=false` | 列出人格 |
| POST | `/api/personas` | 创建人格 |
| GET | `/api/personas/{persona_id}` | 查看人格详情 |
| PUT | `/api/personas/{persona_id}` | 编辑人格正文/规则/边界，并生成新版本 |
| DELETE | `/api/personas/{persona_id}` | 安全归档人格（基础人格不可归档），并清理指向该人格的绑定 |
| POST | `/api/personas/{persona_id}/restore` | 恢复归档人格 |

人格字段：`id`、`name`、`description`、`persona_prompt`、`style_rules`、`behavior_rules`、`permission_boundary`、`version`、`status`、`created_at`、`updated_at`。

### 绑定与注入

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/personas/bindings` | 查看 Agent/Session 绑定 |
| PUT | `/api/personas/bindings/agents/{agent_name}` | 绑定 Agent 默认人格，body: `{ "persona_id": "..." }` |
| DELETE | `/api/personas/bindings/agents/{agent_name}` | 兼容别名：解绑 Agent 默认人格 |
| PUT | `/api/personas/bindings/sessions/{session_id}` | 绑定会话人格 |
| DELETE | `/api/personas/bindings/sessions/{session_id}` | 兼容别名：解绑会话人格 |

解析优先级：请求体 `persona_id` > `session_id` 绑定 > Agent 绑定 > `base-assistant`。`/api/chat`、`/api/chat/stream`、WebSocket `user_message` 和 `/api/agents/{name}/invoke` 都可通过输入数据携带 `persona_id`/`session_id` 生效。

### 自我迭代建议与审核

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/personas/proposals?status=pending` | 列出人格迭代建议 |
| POST | `/api/personas/{persona_id}/proposals` | 基于反馈/管理员指令/反思生成待审核建议 |
| GET | `/api/personas/proposals/{proposal_id}` | 查看建议、diff、summary |
| POST | `/api/personas/proposals/{proposal_id}/approve` | 管理员批准，必须 `admin_approved=true`，生成新版本 |
| POST | `/api/personas/proposals/{proposal_id}/reject` | 管理员拒绝 |
| GET | `/api/personas/{persona_id}/versions` | 查看版本历史 |
| POST | `/api/personas/{persona_id}/rollback` | 回滚到旧版本，必须 `admin_approved=true`，生成新版本 |

安全边界：建议永远以 `pending` 保存，批准前不会修改人格正文；若配置 `PERSONA_ADMIN_TOKEN`，变更/审核接口需要 `X-Admin-Token`。人格提示词注入时被标记为“受控配置”，不得扩大工具、Shell、写入、管理员或系统级权限。

## Artifact / 前端附件 API

- `GET /api/artifacts?session_id=&limit=`：列出 Artifact 元数据。
- `POST /api/artifacts`：创建 Artifact。
  - `kind`: `html | markdown | code | image | file | text`
  - `title`, `content`, `mime_type`, `filename`, `content_encoding(text|base64)`
- `GET /api/artifacts/{id}`：获取元数据。
- `GET /api/artifacts/{id}/content`：获取文本型预览内容。
- `GET /api/artifacts/{id}/download`：作为附件下载。
- `GET /api/artifacts/{id}/open`：inline 打开，用于图片/HTML/文件预览。
- `DELETE /api/artifacts/{id}`：删除 Artifact。

Agent 工具 `create_frontend_artifact` 会返回同样的元数据，前端会从工具结果中自动提取并显示 Artifact chip。


## 人格迭代工具与智能体

`persona_evolution` Agent 挂载受控管理工具 `manage_persona_definition`、`manage_persona_binding`，以及审核式迭代工具 `read_persona_definition`、`record_persona_feedback`、`generate_persona_patch_proposal`、`apply_confirmed_persona_patch`、`list_persona_patch_history`。

- `manage_persona_definition`：`list|get|create|update|archive|delete|restore`，其中 `delete` 等价于安全归档。
- `manage_persona_binding`：`list|resolve|bind_agent|unbind_agent|bind_session|unbind_session`。

所有写入/绑定工具必须显式 `admin_approved=true` 和 `reviewer`，配置 `PERSONA_ADMIN_TOKEN` 时还需要匹配 token。普通 Assistant 遇到 Persona 创建、编辑、禁用或绑定诉求时应委派 `persona_evolution`，不要用 `agent_creator` 创建一个语气 Agent 来替代 Persona。

---

## Agent Run API（v2.5 默认任务模型）

固定 Pipeline 已降级为兼容层。新任务应优先使用 Agent Run：一个 run 对应一个可多开的 agent/session/workspace/task 实例，调度层不假定固定步骤，Agent 根据上下文与工具反馈自主决定下一步。

### 创建运行

`POST /api/runs`

```json
{
  "goal": "实现一个可测试的用户登录 API",
  "agent_name": "assistant",
  "session_id": "chat-001",
  "workspace_id": "login-api",
  "mode": "autonomous",
  "strategy": "agent_decides",
  "input": {}
}
```

返回 `TaskState` 兼容结构，其中 `type=agent_run`，并包含 `run_id`、`task_id`、`agent_name`、`workspace_id`、`progress`、`output_file`。

### 查询与控制

- `GET /api/runs?agent_name=&workspace_id=&session_id=&status=`：列出运行实例。
- `GET /api/runs/{run_id}`：查看单个运行。
- `GET /api/runs/{run_id}/events?offset=0`：读取 transcript 事件流。
- `POST /api/runs/{run_id}/control`，body `{"action":"cancel"}`：请求取消。
- `DELETE /api/runs/{run_id}`：取消运行快捷方式。
- `GET /api/runs/workspaces`：按工作区汇总运行。

### `/api/tasks` 迁移兼容

`POST /api/tasks` 保留，但默认 `pipeline=auto` 会创建 Agent Run，不再执行固定 plan→code→review。只有显式指定 `pipeline` 为某个模板名称时，才走旧 Pipeline 兼容路径。
