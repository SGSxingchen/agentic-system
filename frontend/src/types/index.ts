// ===== 消息和事件 =====

export interface Message {
  id: string
  type: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  memoriesUsed?: number
  elapsedMs?: number
  usage?: TokenUsage
  toolCalls?: ToolCallRecord[]
  progress?: AgentProgressEvent
}

export interface TokenUsage {
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  [key: string]: number | undefined
}

export type ToolCallStatus = 'running' | 'success' | 'error'

export interface ToolCallRecord {
  id: string
  tool: string
  status: ToolCallStatus
  args?: unknown
  result?: unknown
  error?: unknown
  elapsedMs?: number
  startedAt?: string
  finishedAt?: string
  concurrent?: boolean
  truncated?: boolean
}

export interface AgentProgressEvent {
  agent?: string
  activity: 'planning' | 'calling_tool' | 'waiting' | 'completed' | 'running' | string
  status?: 'running' | 'success' | 'error' | 'completed' | string
  message?: string
  tool?: string
  tool_call_id?: string
  current_step?: string
  task_id?: string
  elapsed_ms?: number
  [key: string]: unknown
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

// ===== 任务和管线 =====

// v2 Phase B 起规范状态：pending | running | completed | failed | killed
// planning/coding/reviewing 是旧 routes/tasks.py 残留，保留为 union 项以容忍升级前的旧后端响应。
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'killed'
  | 'planning'
  | 'coding'
  | 'reviewing'

export interface TaskProgress {
  tool_count: number
  total_tokens: number
  activity?: string
  last_tool?: string | null
  current_step?: string | null
}

export interface Task {
  id: string
  task_id?: string
  name?: string
  status: TaskStatus
  requirement?: string
  agent?: string
  pipeline?: string
  input?: any
  output?: any
  plan?: any
  code?: any
  review?: any
  error?: string | null
  progress?: TaskProgress
  output_file?: string | null
  parent_id?: string | null
  ended_at?: string | null
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

export type PanelType = 'chat' | 'tasks' | 'agents' | 'memory' | 'monitor' | 'pipeline' | 'evolution'

// ===== 视图类型（新 Layout 导航） =====

export type ViewType = 'dashboard' | 'tasks' | 'agents' | 'memory' | 'settings'
