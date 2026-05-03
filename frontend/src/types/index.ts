// ===== Artifact / 前端附件 =====

export type ArtifactKind = 'html' | 'markdown' | 'code' | 'image' | 'file' | 'text'

export interface Artifact {
  id: string
  kind: ArtifactKind | string
  title: string
  filename: string
  mime_type: string
  size: number
  previewable: boolean
  session_id?: string | null
  message_id?: string | null
  source?: string
  metadata?: Record<string, any>
  created_at: string
  updated_at: string
  download_url: string
  open_url: string
  content_url: string
}

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
  timeline?: MessageTimelineItem[]
  progress?: AgentProgressEvent
  artifacts?: Artifact[]
}

export type MessageTimelineItemKind = 'text' | 'tool_call'

export interface MessageTimelineItem {
  id: string
  kind: MessageTimelineItemKind
  order: number
  content?: string
  toolCall?: ToolCallRecord
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

export interface AgentInfo {
  name: string
  status: 'idle' | 'busy' | 'error' | 'stopped'
  capabilities: string[]
  description?: string
  system_prompt?: string
  output_format?: string
  max_iterations?: number
  skills?: AgentSkillConfig | null
  mcp_servers?: AgentMCPServerConfig[]
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
  goal?: string
  type?: 'agent_run' | 'pipeline' | 'sub_agent' | string
  run_id?: string | null
  agent_name?: string | null
  session_id?: string | null
  workspace_id?: string | null
  mode?: string
  strategy?: string
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

export interface EvolutionSystemComponent {
  id: string
  title: string
  status: 'healthy' | 'warning' | 'empty' | 'disabled' | string
  summary: string
  metrics: Record<string, any>
  items: Array<Record<string, any>>
  empty_state?: string
}

export interface EvolutionSystemStatus {
  overview: {
    system_name: string
    version: string
    generated_at: string
    readiness: string
    architecture: string
    agent_count: number
    tool_count: number
    dynamic_tool_count: number
    pipeline_count: number
    model: string
    [key: string]: any
  }
  components: EvolutionSystemComponent[]
  graph: EvolutionGraph
}

export interface EvolutionCommand {
  goal: string
  target_components: string[]
  command: string
  status_snapshot: Record<string, any>
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

export type PanelType =
  | 'chat'
  | 'tasks'
  | 'agents'
  | 'memory'
  | 'memory-settings'
  | 'monitor'
  | 'pipeline'
  | 'evolution'
  | 'personas'

// ===== 视图类型（新 Layout 导航） =====

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
