# API 文档

> 最后更新: 2026-06-02 | 基于 `backend/src/api/routes/` 实际代码与 `db26ae4..HEAD` 提交追溯

## 当前 API 总览

当前后端暴露约 98 个 route decorator，主入口如下：

| 模块 | 关键端点 |
|------|----------|
| 健康与配置 | `GET /api/health`、`GET/POST /api/config`、`POST /api/config/models` |
| Agent | `GET/POST /api/agents`、`GET/PUT/DELETE /api/agents/{name}`、`GET /api/agents/configs`、`GET /api/agents/{name}/config`、`POST /api/agents/{name}/invoke`、`POST /api/agents/{name}/mcp/import` |
| 人格绑定 | `GET /api/agents/persona-bindings`、`PUT/DELETE /api/agents/persona-bindings/agents/{agent_name}`、`PUT/DELETE /api/agents/persona-bindings/sessions/{session_id}` |
| Agent Run | `POST /api/runs`、`GET /api/runs`、`GET /api/runs/workspaces`、`GET /api/runs/{run_id}`、`GET /api/runs/{run_id}/events`、`GET /api/runs/{run_id}/memory-context`、`POST /api/runs/{run_id}/control`、`DELETE /api/runs/{run_id}` |
| 任务兼容入口 | `POST /api/tasks`、`GET /api/tasks`、`GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/transcript`、`DELETE /api/tasks/{task_id}` |
| 工作区 | `GET /api/workspaces`、`POST /api/workspaces/import`、`GET/DELETE /api/workspaces/{workspace_id}`、`GET /api/workspaces/{workspace_id}/files`、`GET/PUT /api/workspaces/{workspace_id}/files/content` |
| 聊天室 | `GET/POST /api/chatrooms`、`GET/PUT/DELETE /api/chatrooms/{room_id}`、`GET/POST /api/chatrooms/{room_id}/messages`、`POST /api/chatrooms/{room_id}/invoke`、`POST /api/chatrooms/{room_id}/cancel` |
| 聊天会话 | `GET/POST /api/chat-sessions`、`GET/PUT/DELETE /api/chat-sessions/{session_id}`、`POST /api/chat-sessions/{session_id}/messages` |
| 附件 | `GET/POST /api/attachments`、`GET /api/attachments/{attachment_id}`、`GET /api/attachments/{attachment_id}/content`、`DELETE /api/attachments/{attachment_id}` |
| Artifact | `GET/POST /api/artifacts`、`GET /api/artifacts/{artifact_id}`、`GET /api/artifacts/{artifact_id}/content`、`GET /api/artifacts/{artifact_id}/download`、`GET /api/artifacts/{artifact_id}/open`、`DELETE /api/artifacts/{artifact_id}` |
| 记忆 | `GET /api/memory/stats`、`GET /api/memory/list`、`POST /api/memory/search`、`POST /api/memory/create`、`GET/POST /api/memory/settings`、`PUT/DELETE /api/memory/{memory_id}`、`POST /api/memory/consolidate`、`POST /api/memory/forget` |
| 能力库 | `GET /api/catalog/tools`、`GET /api/catalog/skills`、`GET /api/catalog/mcp`、`POST /api/catalog/{kind}/{name}/assemble`、`POST /api/catalog/{kind}/{name}/unassemble` |
| 人格 | `GET/POST /api/personas`、`GET/PUT/DELETE /api/personas/{persona_id}`、`POST /api/personas/{persona_id}/restore`、`GET /api/personas/{persona_id}/versions`、`POST /api/personas/{persona_id}/rollback`、`GET/POST /api/personas/proposals*` |
| 进化中心 | `GET /api/evolution/graph`、`GET /api/evolution/system-status`、`POST /api/evolution/command`、`GET/PUT /api/evolution/tool-prompts*`、`POST /api/evolution/dynamic-tools`、`POST /api/evolution/reload` |

固定 Pipeline、`/api/pipelines/*`、`config/pipelines.yaml` 和旧 `TaskPanel` 已从现行生产路径移除；当前默认任务模型是 Agent Run。

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
    "agents_registered": 15,
    "version": "0.3.0",
    "uptime": 123,
    "agents": {
      "assistant": "idle",
      "coder": "idle",
      "facilitator": "idle"
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

**路径参数:** `name` — 智能体名称。当前内置关键 Agent 为 `assistant`、`tool_creator`、`agent_creator`、`agent_manager`、`planner`、`coder`、`reviewer`、`persona_evolution`。

**响应:**
```json
{
  "status": "ok",
  "data": {
    "name": "assistant",
    "status": "idle",
    "capabilities": ["memory_search", "planner"],
    "description": "对话协调智能体",
    "system_prompt": "...",
    "output_format": "text",
    "max_iterations": 10,
    "skills": null,
    "mcp_servers": []
  }
}
```

### GET /api/agents/capabilities/list

列出 Agent 管理页可选择的能力（普通 Tool + 已注册 Agent 能力）。注意该路径必须优先于 `/api/agents/{name}` 匹配。

**响应:**
```json
{
  "status": "ok",
  "data": [
    { "name": "web_search", "description": "...", "parameters": { "type": "object" } },
    { "name": "planner", "description": "任务规划智能体", "parameters": { "type": "object" } }
  ]
}
```

### GET /api/agents/configs

列出所有 Agent 的配置视图，包括模型、Tools、MCP、Skills、默认工作区和运行时挂载状态。

`mcp_capability_status.state` 在没有 adapter 时为 `configured_pending_runtime`；当
MCP adapter 接入后，可返回 `proxy_available`、`partial` 或 `adapter_unavailable`。禁用的
MCP server 不应注册代理工具；已注册的 MCP proxy tool 名称必须带 Agent 和 server
作用域，避免不同 Agent 的 `_tools` 互相出现对方工具。

### GET /api/agents/{name}/config

返回单个 Agent 配置视图。响应会对 `llm.api_key` 脱敏，只返回 `api_key_set`。

### POST /api/agents

创建配置化 Agent，写入 `config/agents.yaml` 并热重载。`name` 只能使用字母、数字、下划线且不能以数字开头；`output_format` 仅支持 `text` / `json`。如果热重载失败，后端会回滚本次 YAML 写入并返回明确错误。

**请求体:**
```json
{
  "name": "demo_agent",
  "description": "答辩演示 Agent",
  "system_prompt": "你是...",
  "tools": ["read_file"],
  "output_format": "text",
  "max_iterations": 10,
  "skills": {
    "enabled": true,
    "directories": [],
    "items": [],
    "disabled": [],
    "strategy": "metadata_and_instructions"
  },
  "mcp_servers": []
}
```

### PUT /api/agents/{name}

部分更新配置化 Agent，写入 `config/agents.yaml` 并热重载。支持字段：`description`、`system_prompt`、`tools`、`output_format`、`max_iterations`、`llm`、`model`、`skills`、`mcp_servers`、`default_workspace_id`、`default_workspace_root`。传入 `"skills": null` 表示清除该 Agent 的 skills 配置。响应会对 `llm.api_key` 脱敏，只返回 `api_key_set`。

### POST /api/agents/{name}/mcp/import

把常见 MCP 配置文本导入到指定 Agent 的 `mcp_servers` 列表。接口接受 JSON 或 YAML 文本，支持 Claude Desktop / Cursor 常见的 `mcpServers`、项目当前的 `mcp_servers`、通用 `servers` 和纯数组格式。响应中的 `servers` 与 `preview` 会对 `env` 值脱敏；错误信息不会包含真实环境变量值。

**请求体:**
```json
{
  "content": "{ \"mcpServers\": { \"filesystem\": { \"command\": \"npx\", \"args\": [\"-y\", \"@modelcontextprotocol/server-filesystem\", \".\"], \"env\": {}, \"disabled\": false } } }",
  "format": "json",
  "source": "claude_desktop_config.json",
  "mode": "merge",
  "apply": false
}
```

- `format` 可省略，后端会自动按 JSON/YAML 解析；也可显式传 `json`、`yaml` 或 `yml`。
- `mode=merge` 会按 server `name` 更新同名项并保留未出现在导入内容里的旧 server；`mode=replace` 会用导入结果替换整个列表。
- `apply=false` 只返回预览，不写入；`apply=true` 会写入 `config/agents.yaml` 并热重载，失败时回滚。
- `agent_manager` 不允许通过该普通导入接口直接写入；如需修改其 MCP 挂载，必须走受控 `agent_manager` 工具链。
- `disabled=true` 会映射为 `enabled=false`；未声明 `transport` 时默认 `stdio`。带 `url` 或 `type/transport` 的配置会尽量映射为 `http`、`sse` 或 `streamable_http`，但当前运行时只有 `stdio` server 会真正注册本地代理工具。

### DELETE /api/agents/{name}

删除配置化 Agent 并热重载。为避免误删答辩演示核心角色，内置关键 Agent（`assistant`、`tool_creator`、`agent_creator`、`agent_manager`、`planner`、`coder`、`reviewer`、`persona_evolution`）会返回 `status: "error"`，不能从管理页删除。


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

提交新任务，作为 Agent Run 的便捷入口异步执行。固定模板编排已移除，任务运行由指定 Agent 根据上下文与工具反馈自主推进。

**请求体:**
```json
{
  "requirement": "实现一个用户登录功能",
  "agent_name": "assistant",
  "session_id": "chat-001",
  "workspace_id": "login-api",
  "input": {}
}
```

**响应:**
```json
{
  "status": "ok",
  "message": "任务已提交",
  "data": {
    "task_id": "uuid-xxx",
    "status": "pending",
    "type": "agent_run",
    "agent_name": "assistant",
    "workspace_id": "login-api"
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
      "status": "running",
      "requirement": "实现一个用户登录功能",
      "created_at": "2026-06-02T10:00:00",
      "updated_at": "2026-06-02T10:01:00"
    }
  ]
}
```

### GET /api/tasks/{task_id}

获取任务详情（包含状态、进度、最终输出、错误和 transcript 文件路径等运行信息）。

**路径参数:** `task_id` — 任务 UUID

### GET /api/tasks/{task_id}/transcript

读取任务 transcript JSONL 事件流，支持 `offset` 查询参数。

### DELETE /api/tasks/{task_id}

取消/删除任务。

---

## Agent Run

### POST /api/runs

创建自主 Agent Run 实例。

**请求体:**
```json
{
  "goal": "实现排序算法并给出测试说明",
  "agent_name": "assistant",
  "session_id": "chat-001",
  "workspace_id": "algo-demo",
  "mode": "autonomous",
  "strategy": "agent_decides",
  "max_iterations": 50,
  "completion_criteria": "代码已写入工作区并说明验证方式",
  "auto_memory": true,
  "input": {}
}
```

说明:
- `agent_name` 默认 `assistant`。
- `workspace_id` 为空时，解析顺序为：会话绑定工作区 > Agent 默认工作区 > Agent 默认工作区根目录 > 自动 `run-` 前缀工作区。
- `strategy=agent_decides` 表示调度层不假定固定步骤，由 Agent 自主决定工具调用和下一步动作。
- `auto_memory=true` 时会在运行前召回长期记忆，结束后安排后台反思；请求体里伪造的 `memory_context` 会被忽略。

**响应:**
```json
{
  "status": "ok",
  "message": "运行已创建",
  "data": {
    "run_id": "uuid-xxx",
    "task_id": "uuid-xxx",
    "type": "agent_run",
    "status": "pending",
    "agent_name": "assistant",
    "workspace_id": "algo-demo"
  }
}
```

### GET /api/runs

列出 Agent Run，可按 `agent_name`、`workspace_id`、`session_id`、`status` 过滤。

### GET /api/runs/{run_id}

获取单个运行实例详情。

### GET /api/runs/{run_id}/events

读取运行 transcript 事件流，支持 `offset` 查询参数。

### POST /api/runs/{run_id}/control

控制运行。当前支持:

```json
{ "action": "pause" }
```

`action` 可取 `pause`、`resume`、`cancel`。

### GET /api/runs/{run_id}/memory-context

返回该运行目标可召回的记忆上下文和检索解释，支持 `max_results` 查询参数。该接口用于运行详情页展示“为什么这个 Run 看到了这些记忆”，不会接受前端伪造的 `memory_context`。

### DELETE /api/runs/{run_id}

取消运行快捷入口。

### GET /api/runs/workspaces

按工作区汇总运行数量、活跃运行数、最近更新时间和相关 Agent。

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
      "agents": 15,
      "tools": 22,
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

获取当前 Agentic System Architecture / System State 聚合状态。该接口复用运行时 registry、memory store、Agent Run、bus 和配置文件状态，用于进化页展示系统级架构，而不是把 assistant 或 tool 管理误认为进化本身。

**响应片段:**
```json
{
  "status": "ok",
  "data": {
    "overview": {
      "system_name": "Multi-Agent Code System",
      "readiness": "ready",
      "agent_count": 15,
      "tool_count": 22,
      "run_count": 3,
      "model": "openai / gpt-3.5-turbo"
    },
    "components": [
      {
        "id": "agents",
        "title": "Assistants / Agents",
        "status": "healthy",
        "summary": "assistant 是协作入口之一；planner/coder/reviewer/creator 等 Agent 共同构成运行时。",
        "metrics": { "total": 15, "idle": 15 },
        "items": []
      }
    ],
    "graph": { "summary": { "agents": 15, "tools": 22 } }
  }
}
```

### POST /api/evolution/command

根据用户输入的进化目标和当前系统状态生成一条可提交给 Agent Run 的明确进化指令。生成结果会强调“先审查架构状态，再设计最小可行改造，最后测试验证”，避免把新增 Agent/Tool CRUD 当成进化本身。

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
  "timestamp": "2026-06-02T10:00:00"
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

`persona_evolution` Agent 挂载受控管理工具 `manage_persona_definition`、`manage_persona_binding`，直接更新工具 `update_persona`，以及历史/审核式迭代工具 `read_persona_definition`、`record_persona_feedback`、`generate_persona_patch_proposal`、`apply_confirmed_persona_patch`、`list_persona_patch_history`。

- `manage_persona_definition`：`list|get|create|update|archive|delete|restore`，其中 `delete` 等价于安全归档。
- `manage_persona_binding`：`list|resolve|bind_agent|unbind_agent|bind_session|unbind_session`。
- `update_persona`：A10 之后的默认更新路径，接收 `persona_id + patch`，调用即生效并自动生成版本，审计走 `config_change` 日志和 git 追溯。

`manage_persona_definition` / `manage_persona_binding` 的写入类 operation 仍要求显式 `admin_approved=true` 和 `reviewer`，配置 `PERSONA_ADMIN_TOKEN` 时还需要匹配 token。`update_persona` 不再要求这些审批字段。普通 Assistant 遇到 Persona 创建、编辑、禁用或绑定诉求时应委派 `persona_evolution`，不要用 `agent_creator` 创建一个语气 Agent 来替代 Persona。

---

## Agent Run API（v2.5 默认任务模型）

固定 Pipeline 已移除。当前默认任务模型是 Agent Run：一个 run 对应一个可多开的 agent/session/workspace/task 实例，调度层不假定固定步骤，Agent 根据上下文与工具反馈自主决定下一步。

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

`auto_memory` 默认为 `true`。开启时，Run 会在 Agent 执行前用 `goal` 和 `input.context` 召回长期记忆，将结果注入 Agent payload 的 `memory_context`；运行结束后再把本次 goal/context 与最终输出送入后台记忆反思。设为 `false` 时不会召回，也不会安排反思，并且不会接受请求体里伪造的 `memory_context`。

Run 工作区优先级为：请求 `workspace_id` > 会话绑定工作区 > Agent `default_workspace_id` > Agent `default_workspace_root` > 自动 `run-` 隔离目录。`default_workspace_root` 只允许配置为 `./workspace` 下的相对路径，后端会解析并校验边界后作为可信 `_trusted_workspace_root` 注入。

WebSocket 监控事件 `agent_run_started`、`agent_run_event`、`agent_run_completed` 会携带 `workspace_id`、`session_id`、`auto_memory` 和 `memory_count`，便于前端区分工作区来源与记忆召回状态。

### `/api/tasks` 便捷入口

`POST /api/tasks` 保留为 Agent Run 的便捷入口。请求体使用 `requirement`、`agent_name`、`session_id`、`workspace_id` 和 `input`，不再接受固定模板编排字段。
## Project 工作区与 Agent 级配置补充（v2.6）

### 工作区

- `GET /api/workspaces`：列出已导入的 Project 工作区。
- `POST /api/workspaces/import`：multipart 上传 zip，字段 `file` 必填，`name`、`description` 可选。
- `GET /api/workspaces/{workspace_id}`：获取工作区详情，可通过 `include_files`、`depth`、`limit` 控制文件摘要。
- `DELETE /api/workspaces/{workspace_id}`：删除受管理工作区记录和对应目录。
- `GET /api/workspaces/{workspace_id}/files?path=`：列出工作区内相对路径下的文件。
- `GET /api/workspaces/{workspace_id}/files/content?path=`：读取工作区内文本文件。
- `PUT /api/workspaces/{workspace_id}/files/content`：保存工作区内文本文件，body 为 `path`、`content`、`encoding`。

所有工作区文件路径都是相对路径，后端会拒绝 zip-slip、绝对路径、`..`、Windows 保留名、二进制/过大文本编辑等不安全输入。外部 API 不接受 raw `workspace_root` 作为信任边界；聊天和 Agent 调用只会根据 `workspace_id`、会话绑定或服务端 Agent 配置解析可信工作区根目录。未绑定 Project 的会话会自动获得独立的 `workspace/sessions/{session_id}/` 目录。

### Agent 配置

- `GET /api/agents/configs`：返回所有 Agent 的配置视图，包括模型、Tools、MCP、Skills、默认工作区。
- `GET /api/agents/{name}/config`：返回单个 Agent 配置视图。
- `POST /api/agents` 与 `PUT /api/agents/{name}` 支持 `llm`、`model`、`tools`、`mcp_servers`、`skills`、`default_workspace_id`、`default_workspace_root`。
- `POST /api/agents/{name}/mcp/import`：解析 Claude Desktop / Cursor、项目格式、通用 `servers` 或数组格式的 MCP JSON/YAML 文本，返回脱敏预览；`apply=true` 时按 `merge` 或 `replace` 写入该 Agent 的 `mcp_servers` 并热重载。

`llm` 支持字段：`provider`、`api_key`、`model`、`base_url`、`temperature`、`top_p`、`max_tokens`、`stop_sequences`、`reasoning_effort`、`openai`、`anthropic`。未配置时继承全局 LLM；配置后该 Agent 启动时使用独立 LLM client。响应只返回 `api_key_set`，不会明文返回 Agent 独立密钥。

## Agent 配置管理工具（v2.7）

`agent_manager` 是用于维护既有 Agent 的受控智能体。它只挂载以下工具，不持有 Shell、任意文件写入或任意 YAML 写入能力：

- `read_agent_config`：读取 Agent 配置，密钥只返回 `api_key_set`。
- `validate_agent_config_patch`：校验字段白名单、高风险工具、MCP、模型和工作区字段，不写入。
- `update_agent_config`：A10 之后替代旧 propose/apply 两段式流程，合并字段级 patch 到目标 Agent，调用即生效并触发热重载；热重载失败会回滚。

允许修改的字段仅限：`description`、`system_prompt`、`tools`、`output_format`、`max_iterations`、`llm`、`skills`、`mcp_servers`、`default_workspace_id`、`default_workspace_root`。管理工具本身只能挂到 `agent_manager`；高风险工具治理由字段校验和 `system.yaml` 风险策略兜底。MCP 配置保存后，配置视图无运行态时状态为 `configured_pending_runtime`；运行时会为启用的 stdio server 注册 Agent 作用域代理工具，并进入 `proxy_available`、`partial` 或 `adapter_unavailable` 等运行态。
