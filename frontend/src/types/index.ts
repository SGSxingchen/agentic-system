// ===== 消息和事件 =====

export interface Message {
  id: string
  type: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  memoriesUsed?: number
}

export interface WSEvent {
  type: string
  event_type?: string
  data: any
  timestamp: string
}

// ===== 智能体 =====

export interface AgentInfo {
  name: string
  status: 'idle' | 'busy' | 'error' | 'stopped'
  capabilities: string[]
  description?: string
}

// ===== 记忆 =====

export interface Memory {
  id: string
  type: 'episodic' | 'semantic' | 'procedural'
  content: string
  importance: number
  access_count: number
  created_at: string
  last_accessed?: string
  metadata: Record<string, any>
}

export interface MemoryStats {
  total: number
  total_memories?: number
  by_type: {
    episodic: number
    semantic: number
    procedural: number
  }
  oldest_memory?: string
  newest_memory?: string
}

// ===== 任务和工作流 =====

export type TaskStatus = 'pending' | 'planning' | 'coding' | 'reviewing' | 'running' | 'completed' | 'failed'

export interface Task {
  id: string
  task_id?: string
  name: string
  status: TaskStatus
  requirement?: string
  agent?: string
  input?: any
  output?: any
  plan?: any
  code?: any
  review?: any
  created_at: string
  updated_at?: string
}

// ===== 配置 =====

export interface LLMConfig {
  provider: string
  model: string
  api_key_set: boolean
  base_url?: string
}

export interface SystemConfig {
  llm: LLMConfig
  [key: string]: any
}

// ===== 系统健康 =====

export interface HealthStatus {
  status: string
  bus_running: boolean
  agent_loaded: boolean
  memory_initialized: boolean
  uptime?: number
  version?: string
  agents?: Record<string, string>
}

// ===== API 响应 =====

export interface APIResponse<T = any> {
  status: 'ok' | 'error'
  message?: string
  data?: T
}

// ===== 能力 =====

export interface CapabilityInfo {
  name: string
  description: string
  parameters?: Record<string, any>
}

// ===== 视图类型 =====

export type PanelType = 'chat' | 'tasks' | 'agents' | 'memory' | 'monitor' | 'workflow'

// ===== 视图类型（新 Layout 导航） =====

export type ViewType = 'dashboard' | 'tasks' | 'agents' | 'memory' | 'settings'
