import type {
  AgentMCPServerConfig,
  AgentSkillConfig,
} from '../types'

export interface SkillDraft {
  enabled: boolean
  directoriesText: string
  itemsText: string
  disabledText: string
  strategy: string
}

export interface SkillItemDraft {
  kind: 'inline' | 'path'
  name: string
  description: string
  instructions: string
  path: string
  original?: Record<string, unknown>
}

export interface McpServerDraft {
  name: string
  command: string
  argsText: string
  envText: string
  cwd: string
  enabled: boolean
  description: string
  transport: string
  url: string
}

const DEFAULT_SKILL_STRATEGY = 'metadata_and_instructions'
const DEFAULT_MCP_TRANSPORT = 'stdio'

function linesToList(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

export function emptySkillItemDraft(
  kind: 'inline' | 'path' = 'inline'
): SkillItemDraft {
  return {
    kind,
    name: '',
    description: '',
    instructions: '',
    path: '',
  }
}

export function skillItemToDraft(
  item?: Record<string, unknown> | null
): SkillItemDraft {
  const path = typeof item?.path === 'string' ? item.path : ''
  const hasPathField = Boolean(
    item && Object.prototype.hasOwnProperty.call(item, 'path')
  )
  return {
    kind: hasPathField ? 'path' : 'inline',
    name: typeof item?.name === 'string' ? item.name : '',
    description: typeof item?.description === 'string' ? item.description : '',
    instructions: typeof item?.instructions === 'string' ? item.instructions : '',
    path,
    original: item ? { ...item } : {},
  }
}

export function skillItemDraftToConfig(
  draft: SkillItemDraft
): Record<string, unknown> {
  const original = { ...(draft.original || {}) }
  if (draft.kind === 'path') {
    const path = draft.path.trim()
    if (!path) throw new Error('Path 类型的 Skill 必须填写 SKILL.md 路径。')
    return { ...original, path }
  }

  const name = draft.name.trim()
  if (!name) throw new Error('内联 Skill 必须填写名称。')

  const item: Record<string, unknown> = { ...original, name }
  delete item.path
  const description = draft.description.trim()
  const instructions = draft.instructions.trim()
  if (description) item.description = description
  else delete item.description
  if (instructions) item.instructions = instructions
  else delete item.instructions
  return item
}

export function emptySkillDraft(): SkillDraft {
  return {
    enabled: false,
    directoriesText: '',
    itemsText: '[]',
    disabledText: '',
    strategy: DEFAULT_SKILL_STRATEGY,
  }
}

export function skillConfigToDraft(config?: AgentSkillConfig | null): SkillDraft {
  if (!config) return emptySkillDraft()
  return {
    enabled: config.enabled ?? false,
    directoriesText: (config.directories || []).join('\n'),
    itemsText: formatJson(config.items || []),
    disabledText: (config.disabled || []).join('\n'),
    strategy: config.strategy || DEFAULT_SKILL_STRATEGY,
  }
}

export function buildSkillConfig(draft: SkillDraft): AgentSkillConfig | null {
  let parsedItems: unknown
  try {
    parsedItems = JSON.parse(draft.itemsText.trim() || '[]')
  } catch {
    throw new Error('Skill items 必须是合法的 JSON 数组。')
  }

  if (!Array.isArray(parsedItems)) {
    throw new Error('Skill items 必须是 JSON 数组。')
  }

  const directories = linesToList(draft.directoriesText)
  const disabled = linesToList(draft.disabledText)
  const strategy = draft.strategy.trim()
  const items = parsedItems as Array<Record<string, unknown>>

  if (
    !draft.enabled &&
    directories.length === 0 &&
    items.length === 0 &&
    disabled.length === 0 &&
    !strategy
  ) {
    return null
  }

  return {
    enabled: draft.enabled,
    directories,
    items,
    disabled,
    strategy: strategy || DEFAULT_SKILL_STRATEGY,
  }
}

export function emptyMcpServerDraft(): McpServerDraft {
  return {
    name: '',
    command: '',
    argsText: '',
    envText: '{}',
    cwd: '',
    enabled: true,
    description: '',
    transport: DEFAULT_MCP_TRANSPORT,
    url: '',
  }
}

export function mcpServerToDraft(
  server: AgentMCPServerConfig
): McpServerDraft {
  return {
    name: server.name || '',
    command: server.command || '',
    argsText: (server.args || []).join('\n'),
    envText: formatJson(server.env || {}),
    cwd: server.cwd || '',
    enabled: server.enabled !== false,
    description: server.description || '',
    transport: server.transport || DEFAULT_MCP_TRANSPORT,
    url: server.url || '',
  }
}

export function mcpDraftToServer(
  draft: McpServerDraft
): AgentMCPServerConfig {
  const name = draft.name.trim()
  if (!name) throw new Error('MCP Server 名称不能为空。')

  let parsedEnv: unknown
  try {
    parsedEnv = JSON.parse(draft.envText.trim() || '{}')
  } catch {
    throw new Error('环境变量 JSON 必须是合法对象。')
  }

  if (
    !parsedEnv ||
    typeof parsedEnv !== 'object' ||
    Array.isArray(parsedEnv)
  ) {
    throw new Error('环境变量 JSON 必须是对象，例如 {"TOKEN":"${TOKEN}"}。')
  }

  const env: Record<string, string> = {}
  for (const [key, value] of Object.entries(parsedEnv)) {
    if (!key.trim()) continue
    env[key] = String(value)
  }

  const server: AgentMCPServerConfig = {
    name,
    command: draft.command.trim() || undefined,
    args: linesToList(draft.argsText),
    env,
    cwd: draft.cwd.trim() || undefined,
    enabled: draft.enabled,
    description: draft.description.trim() || undefined,
    transport: draft.transport.trim() || DEFAULT_MCP_TRANSPORT,
  }
  const url = draft.url.trim()
  if (url) server.url = url
  return server
}
