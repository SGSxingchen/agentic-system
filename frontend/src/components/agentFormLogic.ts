import type { APIResponse } from '../types'

export interface AgentFormData {
  name: string
  description: string
  system_prompt: string
  tools: string[]
  output_format: string
  max_iterations: number
  skills_json: string
  mcp_servers_json: string
}

export interface AgentRuntimeConfig {
  skills: Record<string, unknown> | null
  mcpServers: Array<Record<string, unknown>>
}

export interface AgentSaveApi {
  createAgent(data: {
    name: string
    description?: string
    system_prompt?: string
    tools?: string[]
    output_format?: string
    max_iterations?: number
    skills?: Record<string, unknown> | null
    mcp_servers?: Array<Record<string, unknown>>
  }): Promise<APIResponse<unknown>>
  updateAgent(
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
  ): Promise<APIResponse<unknown>>
}

function parseJsonWithLabel(value: string, fallback: unknown, label: string): unknown {
  const trimmed = value.trim()
  if (!trimmed) return fallback
  try {
    return JSON.parse(trimmed)
  } catch (error) {
    const suffix = error instanceof Error ? `：${error.message}` : ''
    throw new Error(`${label} 不是合法 JSON${suffix}`)
  }
}

export function parseAgentRuntimeConfig(form: Pick<AgentFormData, 'skills_json' | 'mcp_servers_json'>): AgentRuntimeConfig {
  const skills = parseJsonWithLabel(form.skills_json, null, 'Skills 配置')
  if (skills !== null && (typeof skills !== 'object' || Array.isArray(skills))) {
    throw new Error('Skills 配置必须是 JSON 对象；不需要高级配置时可留空')
  }

  const mcpServers = parseJsonWithLabel(form.mcp_servers_json, [], 'MCP servers 配置')
  if (!Array.isArray(mcpServers)) {
    throw new Error('MCP servers 配置必须是 JSON 数组；不需要 MCP 时可填写 [] 或留空')
  }

  return {
    skills: skills as Record<string, unknown> | null,
    mcpServers: mcpServers as Array<Record<string, unknown>>,
  }
}

export async function submitAgentForm(params: {
  editingAgent: string | null
  form: AgentFormData
  api: AgentSaveApi
}): Promise<APIResponse<unknown>> {
  const { editingAgent, form, api } = params
  if (!editingAgent) {
    return { status: 'error', message: '当前没有正在编辑的 Agent 表单，请重新打开后再保存' }
  }

  const runtimeConfig = parseAgentRuntimeConfig(form)
  if (editingAgent === '__new__') {
    const name = form.name.trim()
    if (!name) {
      return { status: 'error', message: '名称不能为空' }
    }
    return api.createAgent({
      name,
      description: form.description,
      system_prompt: form.system_prompt,
      tools: form.tools,
      output_format: form.output_format,
      max_iterations: form.max_iterations,
      skills: runtimeConfig.skills,
      mcp_servers: runtimeConfig.mcpServers,
    })
  }

  return api.updateAgent(editingAgent, {
    description: form.description,
    system_prompt: form.system_prompt || undefined,
    tools: form.tools,
    output_format: form.output_format,
    max_iterations: form.max_iterations,
    skills: runtimeConfig.skills,
    mcp_servers: runtimeConfig.mcpServers,
  })
}
