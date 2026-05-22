// ===== 通用 API 响应 =====

export interface APIResponse<T = any> {
  status: 'ok' | 'error'
  message?: string
  data?: T
}

// ===== WebSocket 事件 =====

export interface WSEvent {
  type: string
  event_type?: string
  data: any
  timestamp: string
}

// ===== 智能体 =====

export interface AgentSkillConfig {
  enabled?: boolean
  directories?: string[]
  items?: Array<Record<string, any>>
  disabled?: string[]
  strategy?: string
}

export interface AgentMCPServerConfig {
  name: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  cwd?: string
  enabled?: boolean
  description?: string
  transport?: string
}

export interface AgentLLMConfig {
  provider?: string | null
  api_key_set?: boolean | null
  model?: string | null
  base_url?: string | null
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  reasoning_effort?: string | null
  source?: 'agent_config' | 'global_default' | string
  openai?: Record<string, any>
  anthropic?: Record<string, any>
}

export interface AgentInfo {
  name: string
  status: 'idle' | 'busy' | 'error' | 'stopped'
  capabilities: string[]
  description?: string
  system_prompt?: string
  model?: string | null
  llm?: AgentLLMConfig | null
  output_format?: string
  max_iterations?: number
  skills?: AgentSkillConfig | null
  mcp_servers?: AgentMCPServerConfig[]
  default_workspace_id?: string | null
  default_workspace_root?: string | null
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
  retrieval?: {
    score?: number
    breakdown?: Record<string, number>
    deduped_similar_ids?: string[]
  }
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

export interface MemorySettings {
  backend: string
  persist_dir: string
  collection_name: string
  auto_reflection_enabled: boolean
  reflection_min_turns: number
  reflection_max_messages: number
  recall_max_results: number
  recall_max_chars: number
  recall_score_threshold: number
  fallback_to_memory_on_error: boolean
  consolidation_threshold: number
  forget_after_days: number
  forget_min_importance: number
  status: {
    initialized: boolean
    runtime_store?: string
    note?: string
  }
}

export interface MemoryForgetResult {
  forgotten: number
  [key: string]: any
}

// ===== 任务 / Agent Run =====

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'killed'

export interface TaskProgress {
  tool_count: number
  total_tokens: number
  activity?: string
  last_tool?: string | null
  current_step?: string | null
  memory_count?: number
}

export interface Task {
  id: string
  task_id?: string
  name?: string
  status: TaskStatus
  requirement?: string
  agent?: string
  goal?: string
  type?: 'agent_run' | 'pipeline' | 'sub_agent' | string
  run_id?: string | null
  agent_name?: string | null
  session_id?: string | null
  workspace_id?: string | null
  workspace_root?: string | null
  mode?: string
  strategy?: string
  max_iterations?: number
  iteration?: number
  completion_criteria?: string
  auto_memory?: boolean
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

export interface RunEvent {
  ts: string
  type: string
  payload: Record<string, any>
}

export interface RunEventsResponse {
  run_id: string
  offset: number
  events: RunEvent[]
}

export interface RunWorkspaceSummary {
  workspace_id: string
  path: string
  runs: number
  active_runs: number
  latest_updated_at: string
  agents: string[]
}

export interface RunMemoryContext {
  run_id: string
  query: string
  completion_criteria?: string
  auto_memory?: boolean
  note?: string
  memories: Memory[]
}

// ===== 受管理工作区 =====

export interface WorkspaceFileEntry {
  path: string
  name: string
  type: 'file' | 'directory' | string
  kind?: 'file' | 'directory' | string
  size?: number | null
  updated_at?: string | null
  modified_at?: string | null
}

export interface ManagedWorkspace {
  id: string
  name: string
  kind: string
  source: string
  root_path: string
  created_at: string
  updated_at: string
  metadata?: Record<string, any> & {
    description?: string
    file_count?: number
    directory_count?: number
    total_bytes?: number
  }
  files?: WorkspaceFileEntry[]
}

export interface WorkspaceFileContent {
  workspace_id: string
  path: string
  size: number
  editable: boolean
  is_text: boolean
  encoding: string
  too_large: boolean
  max_editable_bytes: number
  truncated?: boolean
  binary?: boolean
  content: string
}

export interface WorkspaceFileListing {
  workspace_id: string
  path: string
  files: WorkspaceFileEntry[]
}

// ===== 聊天会话 =====

export interface ChatTokenUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  [key: string]: number | undefined
}

export interface ChatToolCallRecord {
  id?: string
  name?: string
  arguments?: Record<string, any> | string
  result?: any
  error?: string
  status?: 'running' | 'success' | 'error' | string
  started_at?: string
  ended_at?: string
}

export interface ChatMessage {
  id: string
  type: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  memoriesUsed?: number
  elapsedMs?: number
  usage?: ChatTokenUsage
  toolCalls?: ChatToolCallRecord[]
  agent_name?: string
  error?: string
}

export interface ChatSessionSummary {
  id: string
  title: string
  workspace_id?: string | null
  created_at: string
  updated_at: string
  last_message?: string
  last_message_preview?: string
  message_count?: number
}

export interface ChatSession extends ChatSessionSummary {
  messages: ChatMessage[]
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

// ===== 能力 =====

export interface CapabilityInfo {
  name: string
  description: string
  parameters?: Record<string, any>
}

// ===== 视图 =====

export type PanelType =
  | 'overview'
  | 'chat'
  | 'workspaces'
  | 'agents'
  | 'runs'
  | 'monitor'
  | 'memory'
  | 'skills'
  | 'mcp'
  | 'personas'
  | 'settings'

export type ViewType = 'dashboard' | 'tasks' | 'agents' | 'memory' | 'settings'

// ===== 人格系统 =====

export interface Persona {
  id: string
  name: string
  description: string
  persona_prompt: string
  style_rules: string[]
  behavior_rules: string[]
  permission_boundary: string
  version: number
  status: 'active' | 'draft' | 'archived'
  created_at: string
  updated_at: string
}

export interface PersonaProposal {
  id: string
  persona_id: string
  base_version: number
  source: 'feedback' | 'admin_instruction' | 'reflection' | string
  session_id?: string | null
  message_id?: string | null
  reflection_id?: string | null
  proposal_text: string
  proposed_patch: Partial<Persona>
  diff: string
  summary: string
  status: 'pending' | 'approved' | 'rejected'
  reviewer?: string | null
  review_time?: string | null
  created_at: string
  updated_at: string
}

export interface PersonaVersion {
  version: number
  persona_id: string
  created_at: string
  reason: string
  snapshot: Persona
  reviewer?: string
  note?: string
}

export interface PersonaBindings {
  agents: Record<string, string>
  sessions: Record<string, string>
  precedence?: string[]
  base_persona_id?: string
  roles?: string[]
}
