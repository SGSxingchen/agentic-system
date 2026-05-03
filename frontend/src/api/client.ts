import type {
  APIResponse,
  AgentInfo,
  Memory,
  MemoryStats,
  MemorySettings,
  HealthStatus,
  SystemConfig,
  Task,
  ChatSession,
  ChatSessionSummary,
  Message,
  EvolutionGraph,
  EvolutionSystemStatus,
  EvolutionCommand,
  ToolPromptInfo,
  Persona,
  PersonaBindings,
  PersonaProposal,
  PersonaVersion,
  Artifact,
} from '../types'

const API_BASE = ''
const DEFAULT_GET_CACHE_TTL_MS = 30_000

interface CachedResponse<T> {
  expiresAt: number
  response?: APIResponse<T>
  promise?: Promise<APIResponse<T>>
}

const getCache = new Map<string, CachedResponse<unknown>>()

function getCached<T>(path: string, ttlMs = DEFAULT_GET_CACHE_TTL_MS): Promise<APIResponse<T>> {
  const now = Date.now()
  const cached = getCache.get(path) as CachedResponse<T> | undefined
  if (cached?.response && cached.expiresAt > now) {
    return Promise.resolve(cached.response)
  }
  if (cached?.promise) {
    return cached.promise
  }

  const promise = get<T>(path).then((response) => {
    if (response.status === 'ok') {
      getCache.set(path, {
        response,
        expiresAt: Date.now() + ttlMs,
      })
    } else {
      getCache.delete(path)
    }
    return response
  }).catch((error) => {
    getCache.delete(path)
    throw error
  })

  getCache.set(path, { promise, expiresAt: now + ttlMs })
  return promise
}

function invalidateGetCache(...prefixes: string[]) {
  if (prefixes.length === 0) {
    getCache.clear()
    return
  }
  for (const key of Array.from(getCache.keys())) {
    if (prefixes.some((prefix) => key.startsWith(prefix))) {
      getCache.delete(key)
    }
  }
}

// ===== 通用请求 helper =====

async function fetchAPI<T>(
  path: string,
  options?: RequestInit
): Promise<APIResponse<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      return {
        status: 'error',
        message: `HTTP ${res.status}: ${text || res.statusText}`,
      }
    }

    const data = await res.json()

    // 后端可能直接返回数据，也可能包装在 { status, data } 中
    if (data && typeof data === 'object' && 'status' in data) {
      return data as APIResponse<T>
    }

    return { status: 'ok', data: data as T }
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : '网络请求失败'
    return { status: 'error', message }
  }
}

function get<T>(path: string): Promise<APIResponse<T>> {
  return fetchAPI<T>(path, { method: 'GET' })
}

function post<T>(path: string, body?: unknown): Promise<APIResponse<T>> {
  return fetchAPI<T>(path, {
    method: 'POST',
    body: body != null ? JSON.stringify(body) : undefined,
  })
}

function put<T>(path: string, body?: unknown): Promise<APIResponse<T>> {
  return fetchAPI<T>(path, {
    method: 'PUT',
    body: body != null ? JSON.stringify(body) : undefined,
  })
}

function del<T>(path: string): Promise<APIResponse<T>> {
  return fetchAPI<T>(path, { method: 'DELETE' })
}

// ===== 配置 API =====

export async function getConfig(): Promise<APIResponse<SystemConfig>> {
  return get<SystemConfig>('/api/config')
}

export async function updateConfig(
  config: Partial<SystemConfig>
): Promise<APIResponse<void>> {
  return post<void>('/api/config', config)
}

export interface ProviderModel {
  id: string
  owned_by?: string | null
  display_name?: string | null
}

export interface ProviderModelList {
  provider: string
  models: ProviderModel[]
}

export async function listProviderModels(params: {
  provider?: string
  base_url?: string
  api_key?: string
}): Promise<APIResponse<ProviderModelList>> {
  return post<ProviderModelList>('/api/config/models', params)
}

// ===== 健康检查 =====

export async function getHealth(): Promise<APIResponse<HealthStatus>> {
  return get<HealthStatus>('/api/health')
}

// ===== 记忆 API =====

export type MemoryStatsResponse = MemoryStats

export async function getMemoryStats(): Promise<APIResponse<MemoryStats>> {
  return get<MemoryStats>('/api/memory/stats')
}

export async function listMemories(
  type?: string,
  limit: number = 20
): Promise<APIResponse<Memory[]>> {
  const params = new URLSearchParams()
  if (type) params.set('type', type)
  params.set('limit', String(limit))
  return get<Memory[]>(`/api/memory/list?${params.toString()}`)
}

export async function searchMemories(
  query: string,
  maxResults: number = 10
): Promise<APIResponse<Memory[]>> {
  return post<Memory[]>('/api/memory/search', {
    query,
    max_results: maxResults,
  })
}

export async function createMemory(data: {
  content: string
  type: string
  importance: number
  metadata?: Record<string, unknown>
}): Promise<APIResponse<Memory>> {
  return post<Memory>('/api/memory/create', {
    ...data,
    metadata: data.metadata || {},
  })
}

export async function updateMemory(
  memoryId: string,
  data: {
    content?: string
    type?: string
    importance?: number
    metadata?: Record<string, unknown>
  }
): Promise<APIResponse<Memory>> {
  return put<Memory>(`/api/memory/${memoryId}`, data)
}

export async function deleteMemory(
  memoryId: string
): Promise<APIResponse<void>> {
  return del<void>(`/api/memory/${memoryId}`)
}

export async function getMemorySettings(): Promise<APIResponse<MemorySettings>> {
  return get<MemorySettings>('/api/memory/settings')
}

export async function updateMemorySettings(
  settings: Partial<MemorySettings>
): Promise<APIResponse<MemorySettings>> {
  return post<MemorySettings>('/api/memory/settings', settings)
}

export async function consolidateMemories(): Promise<APIResponse<Record<string, number>>> {
  return post<Record<string, number>>('/api/memory/consolidate')
}

export async function forgetMemories(): Promise<APIResponse<{ forgotten: number }>> {
  return post<{ forgotten: number }>('/api/memory/forget')
}

// ===== 智能体 API =====

export async function listAgents(): Promise<APIResponse<AgentInfo[]>> {
  return getCached<AgentInfo[]>('/api/agents', 1_000)
}

export async function getAgent(
  name: string
): Promise<APIResponse<AgentInfo>> {
  return get<AgentInfo>(`/api/agents/${name}`)
}

export async function createAgent(data: {
  name: string
  description?: string
  system_prompt?: string
  tools?: string[]
  output_format?: string
  max_iterations?: number
  skills?: Record<string, unknown> | null
  mcp_servers?: Array<Record<string, unknown>>
}): Promise<APIResponse<unknown>> {
  const response = await post('/api/agents', data)
  if (response.status === 'ok') invalidateGetCache('/api/agents')
  return response
}

export async function updateAgent(
  name: string,
  data: {
    description?: string
    system_prompt?: string
    tools?: string[]
    output_format?: string
    max_iterations?: number
    skills?: Record<string, unknown> | null
    mcp_servers?: Array<Record<string, unknown>>
  }
): Promise<APIResponse<unknown>> {
  const response = await put(`/api/agents/${name}`, data)
  if (response.status === 'ok') invalidateGetCache('/api/agents')
  return response
}

export async function deleteAgent(name: string): Promise<APIResponse<void>> {
  const response = await del<void>(`/api/agents/${name}`)
  if (response.status === 'ok') invalidateGetCache('/api/agents')
  return response
}

// ===== 能力 API =====

export async function listCapabilities(): Promise<APIResponse<{ name: string; description: string; parameters?: any }[]>> {
  return getCached('/api/agents/capabilities/list', 60_000)
}

// ===== 进化 API =====

export async function getEvolutionGraph(): Promise<APIResponse<EvolutionGraph>> {
  return get<EvolutionGraph>('/api/evolution/graph')
}

export async function getEvolutionSystemStatus(): Promise<APIResponse<EvolutionSystemStatus>> {
  return get<EvolutionSystemStatus>('/api/evolution/system-status')
}

export async function createEvolutionCommand(
  goal: string
): Promise<APIResponse<EvolutionCommand>> {
  return post<EvolutionCommand>('/api/evolution/command', { goal })
}

export async function createDynamicTool(data: {
  name: string
  description?: string
  mode: 'template' | 'checklist' | 'regex_extract'
  input_schema?: Record<string, unknown>
  config?: Record<string, unknown>
  attach_to_agents?: string[]
  overwrite?: boolean
}): Promise<APIResponse<unknown>> {
  return post('/api/evolution/dynamic-tools', data)
}

export async function reloadEvolutionExtensions(): Promise<APIResponse<unknown>> {
  return post('/api/evolution/reload')
}

export async function getToolPrompts(): Promise<APIResponse<ToolPromptInfo[]>> {
  return get<ToolPromptInfo[]>('/api/evolution/tool-prompts')
}

export async function updateToolPrompt(
  name: string,
  prompt: string
): Promise<APIResponse<unknown>> {
  return put(`/api/evolution/tool-prompts/${encodeURIComponent(name)}`, { prompt })
}

// ===== 聊天 API =====

export async function sendMessage(
  message: string
): Promise<APIResponse<{ response: string; memories_used?: number }>> {
  return post<{ response: string; memories_used?: number }>('/api/chat', {
    message,
  })
}

export async function listChatSessions(): Promise<APIResponse<ChatSessionSummary[]>> {
  return get<ChatSessionSummary[]>('/api/chat-sessions')
}

export async function createChatSession(
  title?: string
): Promise<APIResponse<ChatSession>> {
  return post<ChatSession>('/api/chat-sessions', { title })
}

export async function getChatSession(
  sessionId: string
): Promise<APIResponse<ChatSession>> {
  return get<ChatSession>(`/api/chat-sessions/${encodeURIComponent(sessionId)}`)
}

export async function updateChatSession(
  sessionId: string,
  title: string
): Promise<APIResponse<ChatSession>> {
  return put<ChatSession>(`/api/chat-sessions/${encodeURIComponent(sessionId)}`, {
    title,
  })
}

export async function deleteChatSession(
  sessionId: string
): Promise<APIResponse<void>> {
  return del<void>(`/api/chat-sessions/${encodeURIComponent(sessionId)}`)
}

export async function addChatSessionMessage(
  sessionId: string,
  message: Message
): Promise<APIResponse<ChatSession>> {
  return post<ChatSession>(
    `/api/chat-sessions/${encodeURIComponent(sessionId)}/messages`,
    message
  )
}


// ===== Artifact API =====

export async function listArtifacts(sessionId?: string): Promise<APIResponse<Artifact[]>> {
  const suffix = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  return get<Artifact[]>(`/api/artifacts${suffix}`)
}

export async function getArtifactContent(id: string): Promise<APIResponse<{ artifact: Artifact; content: string }>> {
  return get<{ artifact: Artifact; content: string }>(`/api/artifacts/${encodeURIComponent(id)}/content`)
}

// ===== 任务 API =====

export async function submitTask(
  requirement: string
): Promise<APIResponse<Task>> {
  return post<Task>('/api/tasks', { requirement })
}

export async function getTasks(): Promise<APIResponse<Task[]>> {
  return get<Task[]>('/api/tasks')
}

export async function getTask(
  taskId: string
): Promise<APIResponse<Task>> {
  return get<Task>(`/api/tasks/${taskId}`)
}

export async function deleteTask(
  taskId: string
): Promise<APIResponse<void>> {
  return del<void>(`/api/tasks/${taskId}`)
}

// ===== 智能体调用 =====

export async function getAgents(): Promise<APIResponse<AgentInfo[]>> {
  return listAgents()
}

export async function invokeAgent(
  name: string,
  input: string
): Promise<APIResponse<any>> {
  return post<any>(`/api/agents/${name}/invoke`, { input })
}

// ===== 管线（Pipeline）API =====

export interface PipelineTemplate {
  id: string
  name: string
  description: string
  steps: PipelineStep[]
}

export interface PipelineStep {
  name: string
  agent?: string
  description?: string
  order: number
}

export interface PipelineExecution {
  id: string
  template_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  current_step: number
  total_steps: number
  input: any
  output?: any
  started_at?: string
  completed_at?: string
  steps_status: StepStatus[]
}

export interface StepStatus {
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  output?: any
}

export async function getPipelineTemplates(): Promise<APIResponse<PipelineTemplate[]>> {
  return get<PipelineTemplate[]>('/api/pipelines/templates')
}

export async function executePipeline(
  templateId: string,
  input: Record<string, unknown>
): Promise<APIResponse<PipelineExecution>> {
  return post<PipelineExecution>('/api/pipelines/execute', {
    template_name: templateId,
    requirement: input.user_requirement || input.requirement || '',
    options: input,
  })
}

export async function createPipeline(data: {
  name: string
  description?: string
  mode?: string
  steps?: { name: string; agent: string; input?: Record<string, unknown>; output_key?: string; condition?: string; max_iterations?: number; timeout?: number }[]
}): Promise<APIResponse<unknown>> {
  return post('/api/pipelines', data)
}

export async function updatePipeline(
  name: string,
  data: {
    description?: string
    mode?: string
    steps?: { name: string; agent: string; input?: Record<string, unknown>; output_key?: string; condition?: string; max_iterations?: number; timeout?: number }[]
  }
): Promise<APIResponse<unknown>> {
  return put(`/api/pipelines/${name}`, data)
}

export async function deletePipeline(name: string): Promise<APIResponse<void>> {
  return del<void>(`/api/pipelines/${name}`)
}

export async function getPipelineExecution(
  executionId: string
): Promise<APIResponse<PipelineExecution>> {
  return get<PipelineExecution>(`/api/pipelines/executions/${executionId}`)
}

export async function getPipelineExecutions(): Promise<APIResponse<PipelineExecution[]>> {
  return get<PipelineExecution[]>('/api/pipelines/executions')
}

// ===== 人格系统 API =====


export async function listPersonas(includeArchived = false): Promise<APIResponse<Persona[]>> {
  return getCached<Persona[]>(`/api/personas?include_archived=${includeArchived ? 'true' : 'false'}`)
}

export async function createPersona(data: Partial<Persona> & { name: string }): Promise<APIResponse<Persona>> {
  const response = await post<Persona>('/api/personas', data)
  if (response.status === 'ok') invalidateGetCache('/api/personas', '/api/agents/persona-bindings')
  return response
}

export async function updatePersona(id: string, data: Partial<Persona>): Promise<APIResponse<Persona>> {
  const response = await put<Persona>(`/api/personas/${encodeURIComponent(id)}`, data)
  if (response.status === 'ok') invalidateGetCache('/api/personas', '/api/agents/persona-bindings')
  return response
}

export async function archivePersona(id: string): Promise<APIResponse<Persona>> {
  const response = await del<Persona>(`/api/personas/${encodeURIComponent(id)}`)
  if (response.status === 'ok') invalidateGetCache('/api/personas', '/api/agents/persona-bindings')
  return response
}

export async function restorePersona(id: string): Promise<APIResponse<Persona>> {
  const response = await post<Persona>(`/api/personas/${encodeURIComponent(id)}/restore`)
  if (response.status === 'ok') invalidateGetCache('/api/personas', '/api/agents/persona-bindings')
  return response
}

export async function getAgentPersonaBindings(): Promise<APIResponse<PersonaBindings>> {
  return getCached<PersonaBindings>('/api/agents/persona-bindings')
}

// Compatibility reader for older deployments. New UI should prefer getAgentPersonaBindings().
export async function getPersonaBindings(): Promise<APIResponse<PersonaBindings>> {
  return getCached<PersonaBindings>('/api/personas/bindings')
}

export async function bindAgentPersona(agentName: string, personaId: string): Promise<APIResponse<unknown>> {
  const response = await put(`/api/agents/persona-bindings/agents/${encodeURIComponent(agentName)}`, { persona_id: personaId })
  if (response.status === 'ok') invalidateGetCache('/api/agents/persona-bindings', '/api/personas/bindings')
  return response
}

export async function unbindAgentPersona(agentName: string): Promise<APIResponse<unknown>> {
  const response = await del(`/api/agents/persona-bindings/agents/${encodeURIComponent(agentName)}`)
  if (response.status === 'ok') invalidateGetCache('/api/agents/persona-bindings', '/api/personas/bindings')
  return response
}

export async function bindSessionPersona(sessionId: string, personaId: string): Promise<APIResponse<unknown>> {
  const response = await put(`/api/agents/persona-bindings/sessions/${encodeURIComponent(sessionId)}`, { persona_id: personaId })
  if (response.status === 'ok') invalidateGetCache('/api/agents/persona-bindings', '/api/personas/bindings')
  return response
}

export async function unbindSessionPersona(sessionId: string): Promise<APIResponse<unknown>> {
  const response = await del(`/api/agents/persona-bindings/sessions/${encodeURIComponent(sessionId)}`)
  if (response.status === 'ok') invalidateGetCache('/api/agents/persona-bindings', '/api/personas/bindings')
  return response
}

export async function listPersonaProposals(status?: string): Promise<APIResponse<PersonaProposal[]>> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return getCached<PersonaProposal[]>(`/api/personas/proposals${suffix}`, 10_000)
}

export async function createPersonaProposal(personaId: string, data: {
  source: string
  feedback?: string
  proposal_text?: string
  proposed_patch?: Record<string, unknown>
  session_id?: string
  message_id?: string
  reflection_id?: string
}): Promise<APIResponse<PersonaProposal>> {
  const response = await post<PersonaProposal>(`/api/personas/${encodeURIComponent(personaId)}/proposals`, data)
  if (response.status === 'ok') invalidateGetCache('/api/personas/proposals')
  return response
}

export async function approvePersonaProposal(id: string, reviewer: string, note = ''): Promise<APIResponse<unknown>> {
  const response = await post(`/api/personas/proposals/${encodeURIComponent(id)}/approve`, { reviewer, note, admin_approved: true })
  if (response.status === 'ok') invalidateGetCache('/api/personas')
  return response
}

export async function rejectPersonaProposal(id: string, reviewer: string, note = ''): Promise<APIResponse<PersonaProposal>> {
  const response = await post<PersonaProposal>(`/api/personas/proposals/${encodeURIComponent(id)}/reject`, { reviewer, note })
  if (response.status === 'ok') invalidateGetCache('/api/personas/proposals')
  return response
}

export async function listPersonaVersions(personaId: string): Promise<APIResponse<PersonaVersion[]>> {
  return getCached<PersonaVersion[]>(`/api/personas/${encodeURIComponent(personaId)}/versions`, 10_000)
}

export async function rollbackPersona(personaId: string, version: number, reviewer: string): Promise<APIResponse<Persona>> {
  const response = await post<Persona>(`/api/personas/${encodeURIComponent(personaId)}/rollback`, { version, reviewer, admin_approved: true })
  if (response.status === 'ok') invalidateGetCache('/api/personas')
  return response
}
