import type {
  APIResponse,
  AgentMcpImportPayload,
  AgentMcpImportResult,
  AgentMCPServerConfig,
  AgentInfo,
  AgentSkillConfig,
  ChatSession,
  ChatSessionSummary,
  Chatroom,
  ChatroomCreatePayload,
  ChatroomDispatchTicket,
  ChatroomMessage,
  ChatroomMessageCreateResult,
  ChatroomSummary,
  ChatroomUpdatePayload,
  Memory,
  MemoryStats,
  MemoryForgetResult,
  MemorySettings,
  HealthStatus,
  SystemConfig,
  Task,
  RunEventsResponse,
  RunMemoryContext,
  RunWorkspaceSummary,
  Persona,
  PersonaBindings,
  PersonaProposal,
  PersonaVersion,
  ManagedWorkspace,
  WorkspaceFileContent,
  WorkspaceFileListing,
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

    if (data && typeof data === 'object' && 'status' in data) {
      return data as APIResponse<T>
    }

    return { status: 'ok', data: data as T }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : '网络请求失败'
    return { status: 'error', message }
  }
}

async function fetchFormAPI<T>(
  path: string,
  formData: FormData
): Promise<APIResponse<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      body: formData,
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      return {
        status: 'error',
        message: `HTTP ${res.status}: ${text || res.statusText}`,
      }
    }

    const data = await res.json()
    if (data && typeof data === 'object' && 'status' in data) {
      return data as APIResponse<T>
    }
    return { status: 'ok', data: data as T }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : '网络请求失败'
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

export async function forgetMemories(): Promise<APIResponse<MemoryForgetResult>> {
  return post<MemoryForgetResult>('/api/memory/forget')
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
  model?: string | null
  llm?: Record<string, unknown> | null
  skills?: AgentSkillConfig | null
  mcp_servers?: AgentMCPServerConfig[]
  default_workspace_id?: string
  default_workspace_root?: string
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
    model?: string | null
    llm?: Record<string, unknown> | null
    skills?: AgentSkillConfig | null
    mcp_servers?: AgentMCPServerConfig[]
    default_workspace_id?: string | null
    default_workspace_root?: string | null
  }
): Promise<APIResponse<unknown>> {
  const response = await put(`/api/agents/${name}`, data)
  if (response.status === 'ok') invalidateGetCache('/api/agents')
  return response
}

export async function importAgentMcpConfig(
  name: string,
  payload: AgentMcpImportPayload
): Promise<APIResponse<AgentMcpImportResult>> {
  const response = await post<AgentMcpImportResult>(
    `/api/agents/${encodeURIComponent(name)}/mcp/import`,
    payload
  )
  if (response.status === 'ok') invalidateGetCache('/api/agents')
  return response
}

export async function deleteAgent(name: string): Promise<APIResponse<void>> {
  const response = await del<void>(`/api/agents/${name}`)
  if (response.status === 'ok') invalidateGetCache('/api/agents')
  return response
}

// A8 — 重新装载动态能力 + 刷新 Agent 工具挂载（POST /api/evolution/reload）
export interface EvolutionReloadResult {
  loaded_dynamic_tools?: number
  prompt_overrides?: number
  reloaded_at?: string
  [key: string]: unknown
}

export async function reloadEvolutionExtensions(): Promise<
  APIResponse<EvolutionReloadResult>
> {
  const response = await post<EvolutionReloadResult>('/api/evolution/reload')
  if (response.status === 'ok') {
    invalidateGetCache('/api/agents')
  }
  return response
}

// ===== 能力 API =====

export async function listCapabilities(): Promise<APIResponse<{ name: string; description: string; parameters?: any }[]>> {
  return getCached('/api/agents/capabilities/list', 60_000)
}

// ===== Agent Run API =====

export async function createRun(data: {
  goal: string
  agent_name?: string
  session_id?: string
  workspace_id?: string
  mode?: string
  strategy?: string
  max_iterations?: number
  completion_criteria?: string
  auto_memory?: boolean
  input?: Record<string, unknown>
}): Promise<APIResponse<Task>> {
  return post<Task>('/api/runs', data)
}

export async function getRuns(params?: {
  agent_name?: string
  workspace_id?: string
  session_id?: string
  status?: string
}): Promise<APIResponse<Task[]>> {
  const qs = new URLSearchParams()
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value) qs.set(key, value)
    })
  }
  return get<Task[]>(`/api/runs${qs.toString() ? `?${qs.toString()}` : ''}`)
}

export async function getRun(runId: string): Promise<APIResponse<Task>> {
  return get<Task>(`/api/runs/${runId}`)
}

export async function getRunEvents(runId: string, offset = 0): Promise<APIResponse<RunEventsResponse>> {
  return get<RunEventsResponse>(`/api/runs/${runId}/events?offset=${offset}`)
}

export async function cancelRun(runId: string): Promise<APIResponse<Task>> {
  return del<Task>(`/api/runs/${runId}`)
}

export async function controlRun(
  runId: string,
  action: 'cancel'
): Promise<APIResponse<Task>> {
  return post<Task>(`/api/runs/${runId}/control`, { action })
}

export async function getRunMemoryContext(runId: string): Promise<APIResponse<RunMemoryContext>> {
  return get<RunMemoryContext>(`/api/runs/${runId}/memory-context`)
}

export async function getRunWorkspaces(): Promise<APIResponse<RunWorkspaceSummary[]>> {
  return get<RunWorkspaceSummary[]>('/api/runs/workspaces')
}

// ===== 受管理工作区 API =====

export async function listWorkspaces(): Promise<APIResponse<ManagedWorkspace[]>> {
  return get<ManagedWorkspace[]>('/api/workspaces')
}

export async function getWorkspace(
  workspaceId: string
): Promise<APIResponse<ManagedWorkspace>> {
  return get<ManagedWorkspace>(`/api/workspaces/${encodeURIComponent(workspaceId)}`)
}

export async function importWorkspace(data: {
  file: File
  name?: string
  description?: string
}): Promise<APIResponse<ManagedWorkspace>> {
  const formData = new FormData()
  formData.append('file', data.file)
  if (data.name?.trim()) formData.append('name', data.name.trim())
  if (data.description?.trim()) {
    formData.append('description', data.description.trim())
  }

  return fetchFormAPI<ManagedWorkspace>('/api/workspaces/import', formData)
}

export async function deleteWorkspace(workspaceId: string): Promise<APIResponse<void>> {
  return del<void>(`/api/workspaces/${encodeURIComponent(workspaceId)}`)
}

export async function listWorkspaceFiles(
  workspaceId: string,
  path: string = ''
): Promise<APIResponse<WorkspaceFileListing>> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : ''
  return get<WorkspaceFileListing>(`/api/workspaces/${encodeURIComponent(workspaceId)}/files${qs}`)
}

export async function getWorkspaceFileContent(
  workspaceId: string,
  path: string
): Promise<APIResponse<WorkspaceFileContent>> {
  return get<WorkspaceFileContent>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/files/content?path=${encodeURIComponent(path)}`
  )
}

export async function saveWorkspaceFileContent(
  workspaceId: string,
  data: { path: string; content: string; encoding?: string }
): Promise<APIResponse<{ workspace_id: string; path: string; size: number; updated_at: string }>> {
  return put(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/files/content`,
    {
      path: data.path,
      content: data.content,
      encoding: data.encoding || 'utf-8',
      create_parents: true,
    }
  )
}

// ===== 智能体调用 =====

export async function invokeAgent(
  name: string,
  input: string,
  options?: {
    session_id?: string
    workspace_id?: string
    messages?: Array<{ role: 'user' | 'assistant'; content: string }>
  }
): Promise<APIResponse<any>> {
  const payload: Record<string, unknown> = {
    data: {
      message: input,
      input,
      ...(options?.session_id ? { session_id: options.session_id } : {}),
      ...(options?.workspace_id ? { workspace_id: options.workspace_id } : {}),
      ...(options?.messages ? { messages: options.messages } : {}),
    },
  }
  return post<any>(`/api/agents/${name}/invoke`, payload)
}

// ===== 聊天会话 API =====

export async function listChatSessions(): Promise<APIResponse<ChatSessionSummary[]>> {
  return get<ChatSessionSummary[]>('/api/chat-sessions')
}

export async function createChatSession(data?: {
  title?: string
  workspace_id?: string
}): Promise<APIResponse<ChatSession>> {
  return post<ChatSession>('/api/chat-sessions', data || {})
}

export async function getChatSession(id: string): Promise<APIResponse<ChatSession>> {
  return get<ChatSession>(`/api/chat-sessions/${encodeURIComponent(id)}`)
}

export async function updateChatSession(
  id: string,
  data: { title?: string; workspace_id?: string | null }
): Promise<APIResponse<ChatSession>> {
  return put<ChatSession>(`/api/chat-sessions/${encodeURIComponent(id)}`, data)
}

export async function deleteChatSession(id: string): Promise<APIResponse<void>> {
  return del<void>(`/api/chat-sessions/${encodeURIComponent(id)}`)
}

export async function addChatSessionMessage(
  id: string,
  message: {
    id?: string
    type: 'user' | 'assistant' | 'system'
    content: string
    timestamp?: string
    memoriesUsed?: number
    elapsedMs?: number
    usage?: Record<string, number>
    toolCalls?: Array<Record<string, unknown>>
    agent_name?: string
    error?: string
  }
): Promise<APIResponse<ChatSession>> {
  return post<ChatSession>(
    `/api/chat-sessions/${encodeURIComponent(id)}/messages`,
    message
  )
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

export async function bindSessionPersona(
  sessionId: string,
  personaId: string
): Promise<APIResponse<unknown>> {
  const response = await put(
    `/api/agents/persona-bindings/sessions/${encodeURIComponent(sessionId)}`,
    { persona_id: personaId }
  )
  if (response.status === 'ok')
    invalidateGetCache('/api/agents/persona-bindings', '/api/personas/bindings')
  return response
}

export async function unbindSessionPersona(
  sessionId: string
): Promise<APIResponse<unknown>> {
  const response = await del(
    `/api/agents/persona-bindings/sessions/${encodeURIComponent(sessionId)}`
  )
  if (response.status === 'ok')
    invalidateGetCache('/api/agents/persona-bindings', '/api/personas/bindings')
  return response
}

export async function listPersonaProposals(status?: string): Promise<APIResponse<PersonaProposal[]>> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return getCached<PersonaProposal[]>(`/api/personas/proposals${suffix}`, 10_000)
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

// ===== 聊天室 API =====
// 数据频繁变动，不走 getCached。

export async function listChatrooms(): Promise<APIResponse<ChatroomSummary[]>> {
  return get<ChatroomSummary[]>('/api/chatrooms')
}

export async function getChatroom(id: string): Promise<APIResponse<Chatroom>> {
  return get<Chatroom>(`/api/chatrooms/${encodeURIComponent(id)}`)
}

export async function createChatroom(
  payload: ChatroomCreatePayload
): Promise<APIResponse<Chatroom>> {
  return post<Chatroom>('/api/chatrooms', payload)
}

export async function updateChatroom(
  id: string,
  payload: ChatroomUpdatePayload
): Promise<APIResponse<Chatroom>> {
  return put<Chatroom>(`/api/chatrooms/${encodeURIComponent(id)}`, payload)
}

export async function deleteChatroom(id: string): Promise<APIResponse<void>> {
  return del<void>(`/api/chatrooms/${encodeURIComponent(id)}`)
}

export async function listChatroomMessages(
  id: string,
  since?: string
): Promise<APIResponse<{ messages: ChatroomMessage[] }>> {
  const qs = since ? `?since=${encodeURIComponent(since)}` : ''
  return get<{ messages: ChatroomMessage[] }>(
    `/api/chatrooms/${encodeURIComponent(id)}/messages${qs}`
  )
}

export async function postChatroomMessage(
  id: string,
  content: string
): Promise<APIResponse<ChatroomMessageCreateResult>> {
  return post<ChatroomMessageCreateResult>(
    `/api/chatrooms/${encodeURIComponent(id)}/messages`,
    { content }
  )
}

export async function invokeChatroom(
  id: string,
  agent_name: string,
  prompt?: string
): Promise<APIResponse<ChatroomDispatchTicket>> {
  const body: Record<string, unknown> = { agent_name }
  if (prompt && prompt.trim()) body.prompt = prompt
  return post<ChatroomDispatchTicket>(
    `/api/chatrooms/${encodeURIComponent(id)}/invoke`,
    body
  )
}

export async function cancelChatroom(
  id: string
): Promise<APIResponse<{ cancelled: number }>> {
  return post<{ cancelled: number }>(
    `/api/chatrooms/${encodeURIComponent(id)}/cancel`
  )
}
