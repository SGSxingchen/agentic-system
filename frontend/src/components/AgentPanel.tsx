import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type {
  AgentInfo,
  AgentMCPServerConfig,
  CapabilityInfo,
  Persona,
  PersonaBindings,
} from '../types'
import './AgentPanel.css'

const STATUS_LABEL: Record<string, string> = {
  idle: '空闲',
  busy: '运行中',
  error: '异常',
  stopped: '已停止',
}

function statusPill(status?: string) {
  switch (status) {
    case 'idle':
      return 'pill pill--success'
    case 'busy':
      return 'pill pill--info'
    case 'error':
      return 'pill pill--danger'
    case 'stopped':
    default:
      return 'pill'
  }
}

interface AgentDraft {
  description: string
  system_prompt: string
  output_format: 'text' | 'json'
  max_iterations: number
  tools: string[]
  default_workspace_id: string
  mcp_servers: AgentMCPServerConfig[]
}

function toDraft(agent: AgentInfo): AgentDraft {
  return {
    description: agent.description || '',
    system_prompt: agent.system_prompt || '',
    output_format: agent.output_format === 'json' ? 'json' : 'text',
    max_iterations: agent.max_iterations || 10,
    tools: [...(agent.capabilities || [])],
    default_workspace_id: agent.default_workspace_id || '',
    mcp_servers: agent.mcp_servers ? [...agent.mcp_servers] : [],
  }
}

export function AgentPanel() {
  const { state } = useAppStore()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [detail, setDetail] = useState<AgentInfo | null>(null)
  const [capabilities, setCapabilities] = useState<CapabilityInfo[]>([])
  const [personas, setPersonas] = useState<Persona[]>([])
  const [bindings, setBindings] = useState<PersonaBindings | null>(null)
  const [draft, setDraft] = useState<AgentDraft | null>(null)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const flashNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 2400)
  }

  const loadAgents = useCallback(async () => {
    const res = await api.listAgents()
    if (res.status === 'ok' && Array.isArray(res.data)) {
      const list = res.data
      setAgents(list)
      setSelectedName((current) => current || list[0]?.name || null)
    } else {
      setError(res.message || '加载智能体失败')
    }
  }, [])

  useEffect(() => {
    loadAgents()
    api.listCapabilities().then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) setCapabilities(res.data)
    })
    api.listPersonas().then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) setPersonas(res.data)
    })
    api.getAgentPersonaBindings().then((res) => {
      if (res.status === 'ok' && res.data) setBindings(res.data)
    })
  }, [loadAgents])

  useEffect(() => {
    if (!selectedName) {
      setDetail(null)
      setDraft(null)
      setEditing(false)
      return
    }
    let cancelled = false
    api.getAgent(selectedName).then((res) => {
      if (cancelled) return
      if (res.status === 'ok' && res.data) {
        setDetail(res.data)
        setDraft(toDraft(res.data))
        setEditing(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [selectedName])

  const personaForAgent = useMemo(() => {
    if (!detail || !bindings) return null
    const personaId = bindings.agents?.[detail.name]
    if (!personaId) return null
    return personas.find((p) => p.id === personaId) || null
  }, [detail, bindings, personas])

  const handleSave = async () => {
    if (!detail || !draft) return
    setSaving(true)
    const payload: Record<string, unknown> = {
      description: draft.description,
      system_prompt: draft.system_prompt,
      output_format: draft.output_format,
      max_iterations: draft.max_iterations,
      tools: draft.tools,
      default_workspace_id: draft.default_workspace_id,
    }
    const res = await api.updateAgent(detail.name, payload)
    setSaving(false)
    if (res.status === 'ok') {
      flashNotice('已保存配置')
      setEditing(false)
      await loadAgents()
      const fresh = await api.getAgent(detail.name)
      if (fresh.status === 'ok' && fresh.data) {
        setDetail(fresh.data)
        setDraft(toDraft(fresh.data))
      }
    } else {
      setError(res.message || '保存失败')
    }
  }

  const handleResetDraft = () => {
    if (detail) setDraft(toDraft(detail))
    setEditing(false)
  }

  const toggleTool = (tool: string) => {
    if (!draft) return
    setDraft({
      ...draft,
      tools: draft.tools.includes(tool)
        ? draft.tools.filter((t) => t !== tool)
        : [...draft.tools, tool],
    })
  }

  const renderListItem = (agent: AgentInfo) => {
    const isActive = agent.name === selectedName
    const skillCount = agent.skills?.items?.length || 0
    const mcpCount = agent.mcp_servers?.length || 0
    return (
      <button
        key={agent.name}
        type="button"
        className={`agent-list-row ${isActive ? 'agent-list-row--active' : ''}`}
        onClick={() => setSelectedName(agent.name)}
      >
        <span className="agent-list-row__name">{agent.name}</span>
        <span className={statusPill(agent.status)}>
          {STATUS_LABEL[agent.status] || agent.status}
        </span>
        <span className="agent-list-row__sub">
          {agent.capabilities.length} 工具 · {skillCount} Skills · {mcpCount} MCP
        </span>
      </button>
    )
  }

  const renderToolsPicker = () => {
    if (!draft) return null
    return (
      <div className="agent-tools-picker">
        {capabilities.length === 0 && (
          <div className="empty-state" style={{ padding: 14 }}>
            <span>未发现可用能力</span>
          </div>
        )}
        {capabilities.map((cap) => {
          const checked = draft.tools.includes(cap.name)
          return (
            <div key={cap.name} className="agent-tools-picker__row">
              <input
                id={`tool-${cap.name}`}
                type="checkbox"
                checked={checked}
                disabled={!editing}
                onChange={() => toggleTool(cap.name)}
              />
              <label htmlFor={`tool-${cap.name}`}>
                <strong>{cap.name}</strong>
                <span>{cap.description || '—'}</span>
              </label>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">智能体</h1>
          <div className="page__subtitle">
            智能体是一等实体。所有 Tools / Skills / MCP 以智能体为单位挂载。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" onClick={loadAgents}>
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error">
          <span style={{ flex: 1 }}>{error}</span>
          <button className="btn-xs" onClick={() => setError('')}>
            关闭
          </button>
        </div>
      )}
      {notice && <div className="alert alert--success">{notice}</div>}

      <div className="agents-shell">
        <aside className="agents-list">
          <div className="agents-list__header">
            <span style={{ fontWeight: 600 }}>已注册智能体</span>
            <span className="text-muted">{agents.length} 个</span>
          </div>
          <div className="agents-list__items">
            {agents.length === 0 ? (
              <div className="empty-state">
                <span>暂无智能体</span>
              </div>
            ) : (
              agents.map(renderListItem)
            )}
          </div>
        </aside>

        {detail && draft ? (
          <div className="agent-detail">
            {/* Hero */}
            <section className="agent-detail__hero">
              <div className="agent-detail__hero-title">
                <h2 className="agent-detail__name">{detail.name}</h2>
                <span className={statusPill(detail.status)}>
                  {STATUS_LABEL[detail.status] || detail.status}
                </span>
                <div style={{ flex: 1 }} />
                {!editing ? (
                  <button type="button" className="btn-primary" onClick={() => setEditing(true)}>
                    编辑配置
                  </button>
                ) : (
                  <>
                    <button type="button" onClick={handleResetDraft}>
                      取消
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={handleSave}
                      disabled={saving}
                    >
                      {saving ? '保存中…' : '保存'}
                    </button>
                  </>
                )}
              </div>
              <dl className="agent-detail__hero-meta">
                <div>
                  <dt>角色描述</dt>
                  <dd>{detail.description || '—'}</dd>
                </div>
                <div>
                  <dt>输出格式</dt>
                  <dd>{detail.output_format || 'text'}</dd>
                </div>
                <div>
                  <dt>最大迭代</dt>
                  <dd>{detail.max_iterations ?? '—'}</dd>
                </div>
                <div>
                  <dt>已挂载工具</dt>
                  <dd>{detail.capabilities.length}</dd>
                </div>
              </dl>
            </section>

            {/* 基础信息 */}
            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">基础信息</span>
              </header>
              <div className="agent-section__body">
                <div className="agent-form-grid">
                  <div className="agent-form-field">
                    <label>角色描述</label>
                    <input
                      type="text"
                      value={draft.description}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({ ...draft, description: event.target.value })
                      }
                    />
                  </div>
                  <div className="agent-form-field">
                    <label>输出格式</label>
                    <select
                      value={draft.output_format}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          output_format: event.target.value as 'text' | 'json',
                        })
                      }
                    >
                      <option value="text">text</option>
                      <option value="json">json</option>
                    </select>
                  </div>
                  <div className="agent-form-field">
                    <label>最大迭代次数</label>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={draft.max_iterations}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          max_iterations: Number(event.target.value) || 1,
                        })
                      }
                    />
                  </div>
                  <div className="agent-form-field">
                    <label>默认工作区</label>
                    <select
                      value={draft.default_workspace_id}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          default_workspace_id: event.target.value,
                        })
                      }
                    >
                      <option value="">未指定（运行时由用户选择）</option>
                      {state.workspaces.map((workspace) => (
                        <option key={workspace.id} value={workspace.id}>
                          {workspace.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            </section>

            {/* System Prompt */}
            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">System Prompt</span>
                <span className="text-muted" style={{ fontSize: 11.5 }}>
                  运行时会自动追加 Skills / MCP 描述。
                </span>
              </header>
              <div className="agent-section__body">
                {editing ? (
                  <textarea
                    rows={10}
                    value={draft.system_prompt}
                    onChange={(event) =>
                      setDraft({ ...draft, system_prompt: event.target.value })
                    }
                    style={{
                      width: '100%',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12.5,
                    }}
                  />
                ) : (
                  <div className="agent-system-prompt-block">
                    {draft.system_prompt || '— 未配置 —'}
                  </div>
                )}
              </div>
            </section>

            {/* Tools */}
            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">Tools 挂载</span>
                <span className="text-muted">
                  已选 {draft.tools.length} / {capabilities.length}
                </span>
              </header>
              <div className="agent-section__body">{renderToolsPicker()}</div>
            </section>

            {/* Skills */}
            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">Skills 挂载</span>
                <span className="text-muted">
                  当前为只读视图，编辑请通过 config/agents.yaml
                </span>
              </header>
              <div className="agent-section__body--flush">
                {detail.skills?.items?.length ? (
                  detail.skills.items.map((item, index) => (
                    <div className="agent-section__row" key={index}>
                      <div className="agent-section__row-name">
                        <span>
                          {(item as any).name ||
                            (item as any).id ||
                            `Skill #${index + 1}`}
                        </span>
                        {(item as any).version && (
                          <span className="pill">{(item as any).version}</span>
                        )}
                      </div>
                      <span
                        className="text-muted text-mono"
                        style={{ fontSize: 11.5 }}
                      >
                        {(item as any).source || (item as any).path || ''}
                      </span>
                      {(item as any).description && (
                        <div className="agent-section__row-desc">
                          {(item as any).description}
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="empty-state" style={{ padding: 16 }}>
                    <span>未挂载 Skills</span>
                  </div>
                )}
              </div>
            </section>

            {/* MCP */}
            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">MCP 挂载</span>
                <span className="text-muted">
                  当前为只读视图，编辑请通过 config/agents.yaml
                </span>
              </header>
              <div className="agent-section__body--flush">
                {detail.mcp_servers && detail.mcp_servers.length > 0 ? (
                  detail.mcp_servers.map((server) => (
                    <div className="agent-section__row" key={server.name}>
                      <div className="agent-section__row-name">
                        <span>{server.name}</span>
                        <span
                          className={`pill ${
                            server.enabled ? 'pill--success' : ''
                          }`}
                        >
                          {server.enabled ? '启用' : '关闭'}
                        </span>
                        {server.transport && (
                          <span className="pill">{server.transport}</span>
                        )}
                      </div>
                      <span
                        className="text-muted text-mono"
                        style={{ fontSize: 11.5 }}
                      >
                        {server.command} {server.args?.join(' ')}
                      </span>
                      {server.description && (
                        <div className="agent-section__row-desc">
                          {server.description}
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="empty-state" style={{ padding: 16 }}>
                    <span>未挂载 MCP Server</span>
                  </div>
                )}
              </div>
            </section>

            {/* Default persona */}
            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">默认人格</span>
                <span className="text-muted">于「人格」页统一管理</span>
              </header>
              <div className="agent-section__body">
                {personaForAgent ? (
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>
                      {personaForAgent.name}
                      <span className="pill" style={{ marginLeft: 8 }}>
                        v{personaForAgent.version}
                      </span>
                    </div>
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: 'var(--color-text-secondary)',
                      }}
                    >
                      {personaForAgent.description || '—'}
                    </div>
                  </div>
                ) : (
                  <div className="text-muted" style={{ fontSize: 12.5 }}>
                    未绑定人格，使用基础人格。
                  </div>
                )}
              </div>
            </section>
          </div>
        ) : (
          <div className="agent-detail">
            <section className="agent-detail__hero">
              <div className="empty-state">
                <strong>请选择一个智能体</strong>
                <span>左侧列出已注册的智能体。</span>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
