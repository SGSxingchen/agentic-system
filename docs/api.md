# API 文档

> 最后更新: 2026-04-23 | 基于 backend/src/api/routes/ 实际代码

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
    "bus_running": true,
    "agent_loaded": true,
    "memory_initialized": true,
    "agents_registered": 4
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
        "workspace_root": ""
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
      "workspace_root": ""
    },
    "shell": {
      "enabled": false,
      "timeout": 30
    },
    "custom": {}
  }
}
```

`api_key` 留空会保留已有值；响应中只返回 `api_key_set`，不会明文返回 Key。

**响应:**
```json
{
  "status": "ok",
  "message": "配置已更新并重新加载"
}
```

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

提交新任务，自动发送到 PlannerAgent 开始处理。

**请求体:**
```json
{
  "requirement": "实现一个用户登录功能",
  "workflow": "plan_code_review"
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

## 工作流

### GET /api/workflows/templates

获取预定义工作流模板。

**响应:**
```json
{
  "status": "ok",
  "data": [
    {
      "name": "plan_code_review",
      "description": "标准开发流程: 规划 → 编码 → 审查",
      "steps": ["planner", "coder", "reviewer"]
    },
    {
      "name": "code_only",
      "description": "仅编码: 直接生成代码",
      "steps": ["coder"]
    },
    {
      "name": "code_review",
      "description": "编码+审查: 编码 → 审查",
      "steps": ["coder", "reviewer"]
    },
    {
      "name": "full_pipeline",
      "description": "完整流水线: 规划 → 编码 → 审查 → 测试",
      "steps": ["planner", "coder", "reviewer", "tester"]
    }
  ]
}
```

### POST /api/workflows/execute

执行工作流。

**请求体:**
```json
{
  "requirement": "实现排序算法",
  "workflow_type": "plan_code_review",
  "options": {}
}
```

说明:
- `template_name` 优先级高于 `workflow_type`
- 执行器会把 `requirement` 同时注入为 `user_requirement` / `requirement` / `message`
- 若模板步骤声明 `timeout`，超时会在对应 `step_results` 中返回失败信息

工作流 CRUD 中单个步骤现在支持以下字段:
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
  "message": "工作流 'full_pipeline' 执行完成",
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

### DELETE /api/memory/{memory_id}

删除指定记忆。

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
