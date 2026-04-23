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
      "base_url": ""
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
    "base_url": ""
  }
}
```

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
