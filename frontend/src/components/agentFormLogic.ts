import type { AgentInfo, AgentMCPServerConfig, AgentSkillConfig } from '../types'

export interface AgentDraft {
  description: string
  system_prompt: string
  output_format: 'text' | 'json'
  max_iterations: number
  token_budget: string
  tools: string[]
  skills: AgentSkillConfig | null
  mcp_servers: AgentMCPServerConfig[]
  default_workspace_id: string
  had_agent_llm: boolean
  llm_provider: string
  llm_model: string
  llm_base_url: string
  llm_api_key: string
  llm_temperature: string
  llm_max_tokens: string
}

function isAgentScopedLlm(agent: AgentInfo) {
  return agent.llm?.source === 'agent_config' || (!agent.llm && Boolean(agent.model))
}

function cloneSkills(skills?: AgentSkillConfig | null): AgentSkillConfig | null {
  if (!skills) return null
  return {
    ...skills,
    directories: [...(skills.directories || [])],
    disabled: [...(skills.disabled || [])],
    items: (skills.items || []).map((item) => ({ ...item })),
  }
}

function cloneMcpServers(servers?: AgentMCPServerConfig[]) {
  return (servers || []).map((server) => ({
    ...server,
    args: [...(server.args || [])],
    env: { ...(server.env || {}) },
  }))
}

export function agentToDraft(agent: AgentInfo): AgentDraft {
  const hasAgentLlm = isAgentScopedLlm(agent)

  return {
    description: agent.description || '',
    system_prompt: agent.system_prompt || '',
    output_format: agent.output_format === 'json' ? 'json' : 'text',
    max_iterations: agent.max_iterations || 10,
    token_budget: agent.token_budget != null ? String(agent.token_budget) : '',
    tools: [...(agent.capabilities || [])],
    skills: cloneSkills(agent.skills),
    mcp_servers: cloneMcpServers(agent.mcp_servers),
    default_workspace_id: agent.default_workspace_id || '',
    had_agent_llm: hasAgentLlm,
    llm_provider: hasAgentLlm ? agent.llm?.provider || '' : '',
    llm_model: hasAgentLlm ? agent.llm?.model || agent.model || '' : '',
    llm_base_url: hasAgentLlm ? agent.llm?.base_url || '' : '',
    llm_api_key: '',
    llm_temperature:
      hasAgentLlm && agent.llm?.temperature != null ? String(agent.llm.temperature) : '',
    llm_max_tokens:
      hasAgentLlm && agent.llm?.max_tokens != null ? String(agent.llm.max_tokens) : '',
  }
}

function parseOptionalNumber(label: string, value: string) {
  const trimmed = value.trim()
  if (!trimmed) return undefined

  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} 必须是有效数字`)
  }
  return parsed
}

export function buildAgentUpdatePayload(draft: AgentDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    description: draft.description,
    system_prompt: draft.system_prompt,
    output_format: draft.output_format,
    max_iterations: draft.max_iterations,
    tools: draft.tools,
    skills: draft.skills,
    mcp_servers: draft.mcp_servers,
    default_workspace_id: draft.default_workspace_id || null,
  }

  // A23.3: token_budget — 空字符串表示继承全局，正数表示显式覆盖。
  const tokenBudget = parseOptionalNumber('token 预算上限', draft.token_budget)
  if (tokenBudget !== undefined) {
    payload.token_budget = tokenBudget
  }

  const llm: Record<string, unknown> = {}
  if (draft.llm_provider.trim()) llm.provider = draft.llm_provider.trim()
  if (draft.llm_model.trim()) llm.model = draft.llm_model.trim()
  if (draft.llm_base_url.trim()) llm.base_url = draft.llm_base_url.trim()
  if (draft.llm_api_key.trim()) llm.api_key = draft.llm_api_key.trim()

  const temperature = parseOptionalNumber('模型温度', draft.llm_temperature)
  if (temperature !== undefined) llm.temperature = temperature

  const maxTokens = parseOptionalNumber('最大 Token 数', draft.llm_max_tokens)
  if (maxTokens !== undefined) llm.max_tokens = maxTokens

  if (Object.keys(llm).length > 0) {
    payload.llm = llm
  } else if (draft.had_agent_llm) {
    payload.llm = null
  }

  return payload
}

export function hasAgentDraftChanges(agent: AgentInfo, draft: AgentDraft): boolean {
  return JSON.stringify(draft) !== JSON.stringify(agentToDraft(agent))
}
