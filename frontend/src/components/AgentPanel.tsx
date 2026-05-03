import { useState, useEffect, useCallback } from 'react'
import { useAppStore } from '../store/appStore'
import * as api from '../api/client'
import type { Persona, PersonaBindings } from '../types'
import './AgentPanel.css'

const PERSONA_CACHE_TTL_MS = 30_000

const STATUS_CONFIG: Record<
  string,
  { bg: string; color: string; dotColor: string; label: string }
> = {
  idle: { bg: '#DCFCE7', color: '#166534', dotColor: '#16A34A', label: '空闲' },
  busy: { bg: '#FEF3C7', color: '#92400E', dotColor: '#D97706', label: '忙碌' },
  error: { bg: '#FEE2E2', color: '#991B1B', dotColor: '#DC2626', label: '错误' },
  stopped: { bg: '#F3F4F6', color: '#4B5563', dotColor: '#9CA3AF', label: '已停止' },
}

interface AgentFormData {
  name: string
  description: string
  system_prompt: string
  tools: string[]
  output_format: string
  max_iterations: number
  skills_json: string
  mcp_servers_json: string
}

const EMPTY_FORM: AgentFormData = {
  name: '',
  description: '',
  system_prompt: '',
  tools: [],
  output_format: 'text',
  max_iterations: 10,
  skills_json: JSON.stringify({ enabled: true, directories: [], items: [], disabled: [], strategy: 'metadata_and_instructions' }, null, 2),
  mcp_servers_json: JSON.stringify([], null, 2),
}

interface CapabilityOption {
  name: string
  description: string
}

interface AgentCardData {
  name: string
  status: string
  description?: string
  capabilities?: string[]
  system_prompt?: string
  output_format?: string
  max_iterations?: number
  skills?: any
  mcp_servers?: Array<any>
}

export function AgentPanel() {
  const { state, dispatch } = useAppStore()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [apiAvailable, setApiAvailable] = useState(true)

  // CRUD 状态
  const [editingAgent, setEditingAgent] = useState<string | null>(null)
  const [form, setForm] = useState<AgentFormData>(EMPTY_FORM)
  const [capabilities, setCapabilities] = useState<CapabilityOption[]>([])
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  // 内联工具管理
  const [toolPanelAgent, setToolPanelAgent] = useState<string | null>(null)
  const [toolSaving, setToolSaving] = useState(false)
  const [capabilityFilter, setCapabilityFilter] = useState('')
  const [personas, setPersonas] = useState<Persona[]>([])
  const [personaBindings, setPersonaBindings] = useState<PersonaBindings>({ agents: {}, sessions: {} })
  const [personaNotice, setPersonaNotice] = useState('')
  const [sessionBindId, setSessionBindId] = useState('')
  const [sessionPersonaId, setSessionPersonaId] = useState('base-assistant')

  const fetchAgents = useCallback(async () => {
    setLoading(true)
    const res = await api.listAgents()
    if (res.status === 'ok' && res.data) {
      dispatch({ type: 'SET_AGENTS', payload: res.data })
      setError(null)
      setApiAvailable(true)
    } else {
      setApiAvailable(false)
      setError(null)
    }
    setLoading(false)
  }, [dispatch])

  const fetchCapabilities = useCallback(async () => {
    const res = await api.listCapabilities()
    if (res.status === 'ok' && res.data) {
      setCapabilities(res.data as CapabilityOption[])
    }
  }, [])

  const fetchPersonaContext = useCallback(async (force = false) => {
    const cache = state.personaCache
    const now = Date.now()
    const personasFresh =
      !force &&
      cache.personasFetchedAt > 0 &&
      now - cache.personasFetchedAt < PERSONA_CACHE_TTL_MS &&
      cache.personas.length > 0 &&
      cache.includeArchived === false
    const bindingsFresh =
      !force &&
      cache.bindingsFetchedAt > 0 &&
      now - cache.bindingsFetchedAt < PERSONA_CACHE_TTL_MS &&
      cache.bindings

    if (personasFresh) {
      setPersonas(cache.personas)
      setSessionPersonaId((current) =>
        cache.personas.some((p) => p.id === current)
          ? current
          : cache.personas[0]?.id || 'base-assistant'
      )
    }
    if (bindingsFresh) {
      setPersonaBindings(cache.bindings!)
    }
    if (personasFresh && bindingsFresh) return

    const [personaRes, bindingRes] = await Promise.all([
      personasFresh ? Promise.resolve({ status: 'ok' as const, data: cache.personas }) : api.listPersonas(false),
      bindingsFresh ? Promise.resolve({ status: 'ok' as const, data: cache.bindings! }) : api.getAgentPersonaBindings(),
    ])
    if (personaRes.status === 'ok' && personaRes.data) {
      setPersonas(personaRes.data)
      dispatch({ type: 'SET_PERSONAS_CACHE', payload: { personas: personaRes.data, includeArchived: false } })
      setSessionPersonaId((current) =>
        personaRes.data!.some((p) => p.id === current)
          ? current
          : personaRes.data![0]?.id || 'base-assistant'
      )
    }
    if (bindingRes.status === 'ok' && bindingRes.data) {
      setPersonaBindings(bindingRes.data)
      dispatch({ type: 'SET_PERSONA_BINDINGS_CACHE', payload: { bindings: bindingRes.data } })
    }
  }, [dispatch, state.personaCache])

  useEffect(() => {
    fetchAgents()
    fetchCapabilities()
    fetchPersonaContext()
  }, [fetchAgents, fetchCapabilities, fetchPersonaContext])

  useEffect(() => {
    const timer = setInterval(fetchAgents, 10000)
    return () => clearInterval(timer)
  }, [fetchAgents])

  // 开始创建
  const startCreate = () => {
    setEditingAgent('__new__')
    setForm({ ...EMPTY_FORM })
    setConfirmDelete(null)
    setCapabilityFilter('')
    fetchCapabilities()
  }

  // 开始编辑
  const startEdit = async (agent: AgentCardData) => {
    setEditingAgent(agent.name)
    setForm({
      name: agent.name,
      description: agent.description || '',
      system_prompt: agent.system_prompt || '',
      tools: agent.capabilities || [],
      output_format: agent.output_format || 'text',
      max_iterations: agent.max_iterations || 10,
      skills_json: JSON.stringify(agent.skills || { enabled: true, directories: [], items: [], disabled: [], strategy: 'metadata_and_instructions' }, null, 2),
      mcp_servers_json: JSON.stringify(agent.mcp_servers || [], null, 2),
    })
    setConfirmDelete(null)
    setCapabilityFilter('')
    fetchCapabilities()

    const res = await api.getAgent(agent.name)
    if (res.status === 'ok' && res.data) {
      setForm({
        name: res.data.name,
        description: res.data.description || '',
        system_prompt: res.data.system_prompt || '',
        tools: res.data.capabilities || [],
        output_format: res.data.output_format || 'text',
        max_iterations: res.data.max_iterations || 10,
        skills_json: JSON.stringify(res.data.skills || { enabled: true, directories: [], items: [], disabled: [], strategy: 'metadata_and_instructions' }, null, 2),
        mcp_servers_json: JSON.stringify(res.data.mcp_servers || [], null, 2),
      })
    }
  }

  const cancelEdit = () => {
    setEditingAgent(null)
    setForm(EMPTY_FORM)
    setError(null)
  }

  const toggleTool = (toolName: string) => {
    setForm((prev) => {
      const tools = prev.tools.includes(toolName)
        ? prev.tools.filter((t) => t !== toolName)
        : [...prev.tools, toolName]
      return { ...prev, tools }
    })
  }

  const parseAgentRuntimeConfig = () => {
    const rawSkills = form.skills_json.trim()
    const rawMcp = form.mcp_servers_json.trim()
    const skills = rawSkills ? JSON.parse(rawSkills) : null
    if (skills !== null && (typeof skills !== 'object' || Array.isArray(skills))) {
      throw new Error('Skills 配置必须是 JSON 对象')
    }
    const mcpServers = rawMcp ? JSON.parse(rawMcp) : []
    if (!Array.isArray(mcpServers)) {
      throw new Error('MCP servers 配置必须是 JSON 数组')
    }
    return { skills, mcpServers }
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)

    let runtimeConfig
    try {
      runtimeConfig = parseAgentRuntimeConfig()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Agent scoped 配置 JSON 解析失败')
      setSaving(false)
      return
    }

    let res
    if (editingAgent === '__new__') {
      if (!form.name.trim()) {
        setError('名称不能为空')
        setSaving(false)
        return
      }
      res = await api.createAgent({
        name: form.name.trim(),
        description: form.description,
        system_prompt: form.system_prompt,
        tools: form.tools,
        output_format: form.output_format,
        max_iterations: form.max_iterations,
        skills: runtimeConfig.skills,
        mcp_servers: runtimeConfig.mcpServers,
      })
    } else {
      res = await api.updateAgent(editingAgent!, {
        description: form.description,
        system_prompt: form.system_prompt || undefined,
        tools: form.tools,
        output_format: form.output_format,
        max_iterations: form.max_iterations,
        skills: runtimeConfig.skills,
        mcp_servers: runtimeConfig.mcpServers,
      })
    }

    if (res.status === 'ok') {
      cancelEdit()
      await fetchAgents()
    } else {
      setError(res.message || '保存失败')
    }
    setSaving(false)
  }

  // 内联切换 Agent 的工具（即时保存）
  const handleInlineToggleTool = async (agentName: string, toolName: string, currentTools: string[]) => {
    setToolSaving(true)
    const newTools = currentTools.includes(toolName)
      ? currentTools.filter((t) => t !== toolName)
      : [...currentTools, toolName]

    const res = await api.updateAgent(agentName, { tools: newTools })
    if (res.status === 'ok') {
      await fetchAgents()
    } else {
      setError(res.message || '更新工具失败')
    }
    setToolSaving(false)
  }

  const handleDelete = async (name: string) => {
    const res = await api.deleteAgent(name)
    if (res.status === 'ok') {
      setConfirmDelete(null)
      await fetchAgents()
    } else {
      setError(res.message || '删除失败')
    }
  }


  const bindAgentPersona = async (agentName: string, personaId: string) => {
    const res = await api.bindAgentPersona(agentName, personaId)
    setPersonaNotice(res.status === 'ok' ? `${agentName} 默认人格已更新` : res.message || 'Agent 人格绑定失败')
    dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
    await fetchPersonaContext(true)
  }

  const unbindAgentPersona = async (agentName: string) => {
    const res = await api.unbindAgentPersona(agentName)
    setPersonaNotice(res.status === 'ok' ? `${agentName} 已恢复为基础人格回退` : res.message || 'Agent 人格解绑失败')
    dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
    await fetchPersonaContext(true)
  }

  const bindSessionPersona = async () => {
    if (!sessionBindId.trim()) {
      setPersonaNotice('请输入 session_id')
      return
    }
    const res = await api.bindSessionPersona(sessionBindId.trim(), sessionPersonaId)
    setPersonaNotice(res.status === 'ok' ? `会话 ${sessionBindId.trim()} 已绑定人格` : res.message || '会话人格绑定失败')
    dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
    await fetchPersonaContext(true)
  }

  const unbindSessionPersona = async (sessionId: string) => {
    const res = await api.unbindSessionPersona(sessionId)
    setPersonaNotice(res.status === 'ok' ? `会话 ${sessionId} 已解绑人格` : res.message || '会话人格解绑失败')
    dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
    await fetchPersonaContext(true)
  }

  const personaName = (personaId?: string) => personas.find((p) => p.id === personaId)?.name || personaId || '基础人格'

  const renderPersonaBindingPanel = () => {
    const baseId = personaBindings.base_persona_id || 'base-assistant'
    const activePersonas = personas.filter((persona) => persona.status === 'active')
    const sessionEntries = Object.entries(personaBindings.sessions || {})
    const roles = Array.from(new Set([
      ...(personaBindings.roles || []),
      'assistant',
      'tool_creator',
      'agent_creator',
      'planner',
      'coder',
      'reviewer',
      ...state.agents.map((agent) => agent.name),
    ])).filter(Boolean)

    return (
      <section className="agent-persona-card">
        <div className="agent-persona-card__header">
          <div>
            <span className="agent-form__kicker">Persona Routing</span>
            <h3>Agent 人格路由</h3>
            <p>此处只管理“谁使用哪种人格”。人格定义、版本与审核请到“人格管理”页面。</p>
          </div>
          <button className="refresh-btn" onClick={() => fetchPersonaContext(true)}>刷新人格</button>
        </div>

        {personaNotice && <div className="agent-persona-notice">{personaNotice}</div>}

        <div className="persona-priority-strip">
          <span>1 请求 persona_id</span>
          <span>2 session_id 绑定</span>
          <span>3 Agent 绑定</span>
          <span>4 {personaName(baseId)}</span>
        </div>

        <div className="agent-persona-grid">
          {roles.map((role) => (
            <label key={role} className="agent-persona-row">
              <span>
                <strong>{role}</strong>
                <small>{personaBindings.agents?.[role] ? `已绑定：${personaName(personaBindings.agents?.[role])}` : `未绑定，回退到：${personaName(baseId)}`}</small>
              </span>
              <div className="agent-persona-row__controls">
                <select
                  value={personaBindings.agents?.[role] || baseId}
                  onChange={(event) => bindAgentPersona(role, event.target.value)}
                >
                  {activePersonas.map((persona) => (
                    <option key={persona.id} value={persona.id}>{persona.name} · v{persona.version}</option>
                  ))}
                </select>
                <button type="button" onClick={() => unbindAgentPersona(role)} disabled={!personaBindings.agents?.[role]}>
                  解绑
                </button>
              </div>
            </label>
          ))}
        </div>

        <div className="agent-session-binding">
          <div>
            <h4>会话级绑定</h4>
            <p>用于指定 session_id 的临时/长期会话人格；仍低于请求中显式 persona_id。</p>
          </div>
          <input value={sessionBindId} onChange={(event) => setSessionBindId(event.target.value)} placeholder="session_id" />
          <select value={sessionPersonaId} onChange={(event) => setSessionPersonaId(event.target.value)}>
            {activePersonas.map((persona) => (
              <option key={persona.id} value={persona.id}>{persona.name} · v{persona.version}</option>
            ))}
          </select>
          <button className="btn-primary-sm" onClick={bindSessionPersona}>绑定会话</button>
        </div>

        {sessionEntries.length > 0 && (
          <div className="agent-session-list">
            <h4>当前会话绑定</h4>
            {sessionEntries.map(([sessionId, personaId]) => (
              <div key={sessionId} className="agent-session-row">
                <span><strong>{sessionId}</strong><small>{personaName(personaId)}</small></span>
                <button type="button" onClick={() => unbindSessionPersona(sessionId)}>解绑</button>
              </div>
            ))}
          </div>
        )}
      </section>
    )
  }

  // 渲染编辑表单
  const renderEditForm = () => {
    const isNew = editingAgent === '__new__'
    const normalizedFilter = capabilityFilter.trim().toLowerCase()
    const filteredCapabilities = capabilities.filter((cap) => {
      if (!normalizedFilter) return true
      return (
        cap.name.toLowerCase().includes(normalizedFilter) ||
        (cap.description || '').toLowerCase().includes(normalizedFilter)
      )
    })
    const selectedAgentTools = form.tools.filter((tool) =>
      state.agents.some((agent) => agent.name === tool)
    ).length
    const selectedNativeTools = Math.max(0, form.tools.length - selectedAgentTools)

    return (
      <div className="agent-card agent-card--editing">
        <div className="agent-form">
          <div className="agent-form__hero">
            <div>
              <span className="agent-form__kicker">Agent Config</span>
              <h3 className="agent-form__title">{isNew ? '新建智能体' : `编辑 ${editingAgent}`}</h3>
              <p className="agent-form__subtitle">
                配置角色、工具能力和调用边界。Agent 可以把工具或其他 Agent 当作能力使用。
              </p>
            </div>
            <div className="agent-form__stats">
              <span><strong>{form.tools.length}</strong> 已选能力</span>
              <span><strong>{selectedAgentTools}</strong> 子 Agent</span>
              <span><strong>{selectedNativeTools}</strong> 工具</span>
              <span><strong>{(() => { try { return (JSON.parse(form.skills_json || '{}').items || []).length } catch { return 0 } })()}</strong> Skills</span>
              <span><strong>{(() => { try { return (JSON.parse(form.mcp_servers_json || '[]') || []).length } catch { return 0 } })()}</strong> MCP</span>
            </div>
          </div>

          <div className="agent-form__section">
            <div className="agent-form__section-title">
              <span>01</span>
              <div>
                <h4>基础信息</h4>
                <p>名称用于调用，描述用于让主 Agent 判断什么时候委派它。</p>
              </div>
            </div>

            <div className="agent-form__grid">
              <div className="form-group">
                <label>名称</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  disabled={!isNew}
                  placeholder="如: my_agent"
                />
              </div>

              <div className="form-group">
                <label>描述</label>
                <input
                  type="text"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="智能体功能描述"
                />
              </div>

              <div className="form-group">
                <label>输出格式</label>
                <select
                  value={form.output_format}
                  onChange={(e) => setForm({ ...form, output_format: e.target.value })}
                >
                  <option value="text">text（原样返回）</option>
                  <option value="json">json（自动解析）</option>
                </select>
              </div>

              <div className="form-group">
                <label>最大迭代次数</label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={form.max_iterations}
                  onChange={(e) => setForm({ ...form, max_iterations: parseInt(e.target.value) || 10 })}
                />
                <span className="form-hint">tool_use 循环上限</span>
              </div>
            </div>
          </div>

          <div className="agent-form__section">
            <div className="agent-form__section-title">
              <span>02</span>
              <div>
                <h4>系统提示词</h4>
                <p>写清楚角色、工作流程、工具使用策略和输出约束。</p>
              </div>
            </div>

            <div className="form-group">
              <textarea
                className="prompt-editor"
                value={form.system_prompt}
                onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                placeholder="定义智能体的角色、行为和输出格式..."
                rows={10}
              />
              <span className="form-hint">支持 Markdown。编辑已有 Agent 时会加载当前配置中的 Prompt。</span>
            </div>
          </div>

          <div className="agent-form__section">
            <div className="agent-form__section-title agent-form__section-title--tools">
              <span>03</span>
              <div>
                <h4>可用能力</h4>
                <p>选择这个 Agent 可以调用的工具或子 Agent。</p>
              </div>
              <input
                className="tool-search"
                type="search"
                value={capabilityFilter}
                onChange={(e) => setCapabilityFilter(e.target.value)}
                placeholder="搜索工具或 Agent"
              />
            </div>

            <div className="tools-selector">
              {filteredCapabilities.length > 0 ? (
                filteredCapabilities.map((cap) => {
                  const active = form.tools.includes(cap.name)
                  const isAgentTool = state.agents.some((agent) => agent.name === cap.name)
                  return (
                    <label
                      key={cap.name}
                      className={`tool-checkbox ${active ? 'tool-checkbox--active' : ''}`}
                      title={cap.description}
                    >
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={() => toggleTool(cap.name)}
                      />
                      <span className="tool-checkbox__mark" />
                      <span className="tool-checkbox__body">
                        <span className="tool-name">
                          {cap.name}
                          {isAgentTool && <span className="tool-kind-badge">Agent</span>}
                        </span>
                        {cap.description && <span className="tool-desc">{cap.description}</span>}
                      </span>
                    </label>
                  )
                })
              ) : (
                <span className="form-hint">没有匹配的工具或 Agent</span>
              )}
            </div>
            <span className="form-hint">LLM 会根据 Prompt 和上下文自主决定何时使用这些能力。</span>
          </div>

          <div className="agent-form__section agent-form__section--runtime">
            <div className="agent-form__section-title">
              <span>04</span>
              <div>
                <h4>Skills 与 MCP（Agent 专属）</h4>
                <p>只保存到当前 Agent。启动/调用该 Agent 时，才会加载启用的 SKILL.md 元数据和 MCP server 定义。</p>
              </div>
            </div>

            <div className="agent-runtime-grid">
              <div className="form-group">
                <label>Skills JSON</label>
                <textarea
                  className="runtime-json-editor"
                  value={form.skills_json}
                  onChange={(e) => setForm({ ...form, skills_json: e.target.value })}
                  rows={11}
                  spellCheck={false}
                />
                <span className="form-hint">支持 directories、items、disabled、strategy；items 可内联 name/description/instructions 或 path。</span>
              </div>

              <div className="form-group">
                <label>MCP servers JSON</label>
                <textarea
                  className="runtime-json-editor"
                  value={form.mcp_servers_json}
                  onChange={(e) => setForm({ ...form, mcp_servers_json: e.target.value })}
                  rows={11}
                  spellCheck={false}
                />
                <span className="form-hint">数组项字段：name、command、args、env、cwd、enabled、description、transport。</span>
              </div>
            </div>
          </div>

          {error && <div className="agent-error">{error}</div>}

          <div className="button-group agent-form__actions">
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
            <button className="btn-secondary" onClick={cancelEdit}>取消</button>
          </div>
        </div>
      </div>
    )
  }

  const renderAgentCard = (agent: AgentCardData) => {
    const statusCfg = STATUS_CONFIG[agent.status] || STATUS_CONFIG.stopped
    const isConfirming = confirmDelete === agent.name
    const toolCount = agent.capabilities?.length || 0
    const delegatedAgentCount = (agent.capabilities || []).filter((cap) =>
      state.agents.some((item) => item.name === cap)
    ).length
    const skillCount = Array.isArray(agent.skills?.items) ? agent.skills.items.length : 0
    const mcpCount = Array.isArray(agent.mcp_servers) ? agent.mcp_servers.filter((server) => server.enabled !== false).length : 0

    return (
      <div key={agent.name} className="agent-card">
        <div className="agent-card-header">
          <div className="agent-name-row">
            <span className="agent-status-dot" style={{ backgroundColor: statusCfg.dotColor }} />
            <h3 className="agent-name">{agent.name}</h3>
          </div>
          <div className="agent-card__actions">
            <span className="agent-status-badge" style={{ background: statusCfg.bg, color: statusCfg.color }}>
              {statusCfg.label}
            </span>
            <button className="btn-icon" onClick={() => startEdit(agent)} title="编辑">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
            </button>
            <button className="btn-icon btn-icon--danger" onClick={() => setConfirmDelete(agent.name)} title="删除">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>
        </div>

        {isConfirming && (
          <div className="confirm-strip">
            <span>确认删除 "{agent.name}"？</span>
            <button className="btn-danger-sm" onClick={() => handleDelete(agent.name)}>确定</button>
            <button className="btn-secondary-sm" onClick={() => setConfirmDelete(null)}>取消</button>
          </div>
        )}

        {agent.description && <p className="agent-description">{agent.description}</p>}

        <div className="agent-card-meta">
          <span>{toolCount} 个能力</span>
          <span>{delegatedAgentCount} 个子 Agent</span>
          <span>{agent.output_format || 'text'}</span>
          <span>{skillCount} skills</span>
          <span>{mcpCount} MCP</span>
        </div>

        {/* 当前工具标签 + 管理按钮 */}
        <div className="agent-tools-section">
          <div className="agent-capabilities">
            {(agent.capabilities || []).map((cap) => {
              const isAgentTool = state.agents.some((a) => a.name === cap)
              return (
                <span key={cap} className={`capability-tag ${isAgentTool ? 'capability-tag--agent' : ''}`}>
                  {cap}
                  <button
                    className="capability-tag__remove"
                    title={`移除 ${cap}`}
                    disabled={toolSaving}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleInlineToggleTool(agent.name, cap, agent.capabilities || [])
                    }}
                  >x</button>
                </span>
              )
            })}
            <button
              className="capability-tag capability-tag--add"
              onClick={() => {
                setToolPanelAgent(toolPanelAgent === agent.name ? null : agent.name)
                fetchCapabilities()
              }}
            >+ 工具</button>
          </div>

          {/* 展开的工具选择面板 */}
          {toolPanelAgent === agent.name && (
            <div className="tool-picker">
              <div className="tool-picker__header">
                <span className="tool-picker__title">可用工具</span>
                <button className="tool-picker__close" onClick={() => setToolPanelAgent(null)}>x</button>
              </div>
              <div className="tool-picker__list">
                {capabilities
                  .filter((cap) => cap.name !== agent.name)  /* 不能选自己 */
                  .map((cap) => {
                    const active = (agent.capabilities || []).includes(cap.name)
                    const isAgentCap = state.agents.some((a) => a.name === cap.name)
                    return (
                      <label key={cap.name} className={`tool-picker__item ${active ? 'tool-picker__item--active' : ''}`}>
                        <input
                          type="checkbox"
                          checked={active}
                          disabled={toolSaving}
                          onChange={() => handleInlineToggleTool(agent.name, cap.name, agent.capabilities || [])}
                        />
                        <span className="tool-picker__name">
                          {cap.name}
                          {isAgentCap && <span className="tool-picker__badge">Agent</span>}
                        </span>
                        {cap.description && <span className="tool-picker__desc">{cap.description}</span>}
                      </label>
                    )
                  })}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  if (loading && state.agents.length === 0) {
    return (
      <div className="agent-panel">
        <div className="panel-header"><h2>智能体管理</h2></div>
        <div className="agent-loading">
          <div className="loading-spinner" />
          <p>加载中...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="agent-panel">
      <div className="panel-header">
        <h2>智能体管理</h2>
        <div className="panel-header__actions">
          <button className="btn-primary-sm" onClick={startCreate} disabled={editingAgent !== null}>
            + 新建智能体
          </button>
          <button className="refresh-btn" onClick={fetchAgents}>刷新</button>
        </div>
      </div>

      {!apiAvailable && (
        <div className="agent-error" style={{ borderColor: 'rgba(217, 119, 6, 0.2)', background: 'rgba(217, 119, 6, 0.06)', color: 'var(--color-warning)' }}>
          未连接到后端，部分功能不可用
        </div>
      )}

      {error && !editingAgent && <div className="agent-error">{error}</div>}

      {renderPersonaBindingPanel()}

      {editingAgent === '__new__' && renderEditForm()}
      {editingAgent && editingAgent !== '__new__' && renderEditForm()}

      {state.agents.length === 0 && !editingAgent ? (
        <div className="agent-empty">
          <p>暂无已注册的智能体，点击上方按钮创建</p>
        </div>
      ) : (
        <div className="agent-grid">
          {state.agents
            .filter((a) => a.name !== editingAgent || editingAgent === '__new__')
            .map((agent) => renderAgentCard(agent))}
        </div>
      )}
    </div>
  )
}
