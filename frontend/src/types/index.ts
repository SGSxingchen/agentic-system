// ===== 消息和事件 =====

export interface Message {
  id: string
  type: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  memoriesUsed?: number
  elapsedMs?: number
  usage?: TokenUsage
}

export interface TokenUsage {
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  [key: string]: number | undefined
}

export interface ChatSessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  last_message?: string
}

export interface ChatSession extends ChatSessionSummary {
  messages: Message[]
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
  system_prompt?: string
  output_format?: string
  max_iterations?: number
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
  temperature?: number
  top_p?: number | null
  max_tokens?: number
  stop_sequences?: string[]
  openai?: {
    max_completion_tokens?: number | null
    use_legacy_max_tokens?: boolean
    presence_penalty?: number | null
    frequency_penalty?: number | null
    reasoning_effort?: string
    seed?: number | null
  }
  anthropic?: {
    top_k?: number | null
  }
}

export interface ToolsConfig {
  web_search: {
    provider: string
    base_url?: string
    api_key_set: boolean
    max_results: number
    timeout: number
  }
  web_fetch: {
    timeout: number
    max_chars: number
  }
  file: {
    workspace_root?: string
  }
  shell: {
    enabled: boolean
    timeout: number
  }
  custom?: Record<string, {
    enabled: boolean
    base_url?: string
    api_key_set: boolean
    extra?: Record<string, any>
  }>
}

export interface SystemConfig {
  llm: LLMConfig
  tools?: ToolsConfig
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

// ===== 进化能力图 =====

export interface EvolutionNode {
  id: string
  label: string
  type: 'agent' | 'tool' | 'dynamic_tool'
  description?: string
  status?: string
  capabilities?: string[]
  parameters?: Record<string, any>
  mode?: string | null
}

export interface EvolutionEdge {
  source: string
  target: string
  kind: 'uses' | 'delegates'
}

export interface EvolutionGraph {
  summary: {
    agents: number
    tools: number
    dynamic_tools: number
    edges: number
    master_agent?: string | null
  }
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
  supported_dynamic_modes: string[]
  extension_points: string[]
}

export interface ToolPromptInfo {
  name: string
  type: 'tool' | 'dynamic_tool'
  prompt: string
  prompt_source: 'default' | 'custom'
  schema: Record<string, any>
  returns?: string
  mode?: string | null
}

// ===== 视图类型 =====

export type PanelType = 'chat' | 'tasks' | 'agents' | 'memory' | 'monitor' | 'workflow' | 'evolution'

// ===== 视图类型（新 Layout 导航） =====

export type ViewType = 'dashboard' | 'tasks' | 'agents' | 'memory' | 'settings'
