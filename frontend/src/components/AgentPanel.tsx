import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type {
  AgentInfo,
  AgentMCPServerConfig,
  AgentSkillConfig,
  CapabilityInfo,
  Persona,
  PersonaBindings,
} from '../types'
import {
  agentToDraft,
  buildAgentUpdatePayload,
  hasAgentDraftChanges,
  type AgentDraft,
} from './agentFormLogic'
import {
  mcpDraftToServer,
  mcpServerToDraft,
  skillItemDraftToConfig,
  skillItemToDraft,
} from './skillMcpFormLogic'
import { Select } from './Select'
import './AgentPanel.css'

type EditableMcpServer = AgentMCPServerConfig & { _envText?: string }

const STATUS_LABEL: Record<string, string> = {
  idle: '空闲',
  busy: '运行中',
  error: '异常',
  stopped: '已停止',
}

const DEFAULT_SKILLS: AgentSkillConfig = {
  enabled: false,
  directories: [],
  items: [],
  disabled: [],
  strategy: 'metadata_and_instructions',
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

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function normalizeSkills(skills: AgentSkillConfig | null): AgentSkillConfig | null {
  if (!skills) return null
  const items = (skills.items || []).map((item) =>
    skillItemDraftToConfig(skillItemToDraft(item))
  )
  const directories = skills.directories || []
  const disabled = skills.disabled || []
  const strategy = skills.strategy?.trim() || 'metadata_and_instructions'
  if (
    skills.enabled !== true &&
    directories.length === 0 &&
    disabled.length === 0 &&
    items.length === 0
  ) {
    return null
  }
  return {
    enabled: skills.enabled ?? false,
    directories,
    items,
    disabled,
    strategy,
  }
}

function normalizeMcpServers(servers: AgentMCPServerConfig[]) {
  return servers.map((server) => {
    const draft = mcpServerToDraft(server)
    const envText = (server as EditableMcpServer)._envText
    if (envText != null) draft.envText = envText
    return mcpDraftToServer(draft)
  })
}

function createEmptyMcpServer(): AgentMCPServerConfig {
  return {
    name: '',
    command: '',
    args: [],
    env: {},
    enabled: true,
    transport: 'stdio',
    cwd: '',
    description: '',
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
  const [importingMcp, setImportingMcp] = useState(false)
  const [mcpImportText, setMcpImportText] = useState('')
  const [mcpImportMode, setMcpImportMode] = useState<'merge' | 'replace'>('merge')
  const [mcpImportFormat, setMcpImportFormat] = useState<'auto' | 'json' | 'yaml'>('auto')
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
        setDraft(agentToDraft(res.data))
        setEditing(false)
        setMcpImportText('')
      } else {
        setError(res.message || '加载智能体详情失败')
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

  const updateDraft = (patch: Partial<AgentDraft>) => {
    if (!draft) return
    setDraft({ ...draft, ...patch })
  }

  const handleSave = async () => {
    if (!detail || !draft) return
    let payload: Record<string, unknown>
    try {
      payload = buildAgentUpdatePayload({
        ...draft,
        skills: normalizeSkills(draft.skills),
        mcp_servers: normalizeMcpServers(draft.mcp_servers),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Agent 配置不合法')
      return
    }
    setSaving(true)
    const res = await api.updateAgent(detail.name, payload)
    setSaving(false)
    if (res.status === 'ok') {
      flashNotice('配置已保存')
      setEditing(false)
      await loadAgents()
      const fresh = await api.getAgent(detail.name)
      if (fresh.status === 'ok' && fresh.data) {
        setDetail(fresh.data)
        setDraft(agentToDraft(fresh.data))
      }
    } else {
      setError(res.message || '保存失败')
    }
  }

  const handleResetDraft = () => {
    if (detail) setDraft(agentToDraft(detail))
    setEditing(false)
    setMcpImportText('')
  }

  const updateSkills = (patch: Partial<AgentSkillConfig>) => {
    if (!draft) return
    setDraft({
      ...draft,
      skills: {
        ...DEFAULT_SKILLS,
        ...(draft.skills || {}),
        ...patch,
      },
    })
  }

  const clearSkills = () => updateDraft({ skills: null })

  const updateSkillItem = (index: number, item: Record<string, unknown>) => {
    if (!draft) return
    const skills = { ...DEFAULT_SKILLS, ...(draft.skills || {}) }
    const items = [...(skills.items || [])]
    items[index] = item
    updateSkills({ items })
  }

  const addSkillItem = (kind: 'inline' | 'path') => {
    const skills = { ...DEFAULT_SKILLS, ...(draft?.skills || {}) }
    updateSkills({
      items: [
        ...(skills.items || []),
        kind === 'path' ? { path: '' } : { name: '', description: '', instructions: '' },
      ],
    })
  }

  const removeSkillItem = (index: number) => {
    if (!draft) return
    const skills = { ...DEFAULT_SKILLS, ...(draft.skills || {}) }
    updateSkills({ items: (skills.items || []).filter((_, idx) => idx !== index) })
  }

  const updateMcpServer = (index: number, patch: Partial<EditableMcpServer>) => {
    if (!draft) return
    const servers = [...draft.mcp_servers]
    servers[index] = { ...servers[index], ...patch }
    updateDraft({ mcp_servers: servers })
  }

  const addMcpServer = () => {
    if (!draft) return
    updateDraft({ mcp_servers: [...draft.mcp_servers, createEmptyMcpServer()] })
  }

  const removeMcpServer = (index: number) => {
    if (!draft) return
    updateDraft({ mcp_servers: draft.mcp_servers.filter((_, idx) => idx !== index) })
  }

  const handleImportMcp = async () => {
    if (!detail || !draft || !mcpImportText.trim()) return
    if (hasAgentDraftChanges(detail, draft)) {
      setError('当前 Agent 配置有未保存草稿。请先保存或取消当前修改，再导入 MCP 配置。')
      return
    }
    setImportingMcp(true)
    setError('')
    const res = await api.importAgentMcpConfig(detail.name, {
      content: mcpImportText,
      format: mcpImportFormat,
      mode: mcpImportMode,
      apply: true,
    })
    setImportingMcp(false)
    if (res.status === 'ok') {
      setMcpImportText('')
      flashNotice('MCP 配置已导入并保存')
      await loadAgents()
      const fresh = await api.getAgent(detail.name)
      if (fresh.status === 'ok' && fresh.data) {
        setDetail(fresh.data)
        setDraft(agentToDraft(fresh.data))
      } else if (res.data?.agent) {
        setDetail(res.data.agent)
        setDraft(agentToDraft(res.data.agent))
      }
      return
    }
    setError(res.data?.errors?.join('；') || res.message || 'MCP 导入失败')
  }

  const toggleTool = (tool: string) => {
    if (!draft) return
    updateDraft({
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
                <span>{cap.description || '-'}</span>
              </label>
            </div>
          )
        })}
      </div>
    )
  }

  const renderSkillsEditor = () => {
    if (!draft) return null
    const skills = { ...DEFAULT_SKILLS, ...(draft.skills || {}) }
    const items = skills.items || []
    return (
      <div className="agent-config-editor">
        <div className="agent-inline-actions">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={skills.enabled === true}
              disabled={!editing}
              onChange={(event) => updateSkills({ enabled: event.target.checked })}
            />
            <span>启用 Skills 加载</span>
          </label>
          <button type="button" onClick={() => addSkillItem('inline')} disabled={!editing}>
            添加内联 Skill
          </button>
          <button type="button" onClick={() => addSkillItem('path')} disabled={!editing}>
            添加路径 Skill
          </button>
          <button type="button" className="btn-danger" onClick={clearSkills} disabled={!editing}>
            清空
          </button>
        </div>

        <div className="agent-form-grid">
          <label className="agent-form-field">
            <span>加载策略</span>
            <input
              value={skills.strategy || ''}
              disabled={!editing}
              onChange={(event) => updateSkills({ strategy: event.target.value })}
              placeholder="metadata_and_instructions"
            />
          </label>
          <label className="agent-form-field">
            <span>禁用项</span>
            <textarea
              rows={3}
              value={(skills.disabled || []).join('\n')}
              disabled={!editing}
              onChange={(event) => updateSkills({ disabled: splitLines(event.target.value) })}
              placeholder="每行一个 Skill 名称"
            />
          </label>
        </div>

        <label className="agent-form-field">
          <span>Skill 目录</span>
          <textarea
            rows={3}
            value={(skills.directories || []).join('\n')}
            disabled={!editing}
            onChange={(event) => updateSkills({ directories: splitLines(event.target.value) })}
            placeholder="./skills"
          />
        </label>

        <div className="agent-edit-list">
          {items.length === 0 ? (
            <div className="empty-state" style={{ padding: 16 }}>
              <span>未挂载 Skills</span>
            </div>
          ) : (
            items.map((item, index) => {
              const itemDraft = skillItemToDraft(item)
              return (
                <div className="agent-edit-row" key={index}>
                  <div className="agent-edit-row__top">
                    <select
                      value={itemDraft.kind}
                      disabled={!editing}
                      onChange={(event) =>
                        updateSkillItem(
                          index,
                          event.target.value === 'path'
                            ? { path: '' }
                            : { name: '', description: '', instructions: '' }
                        )
                      }
                    >
                      <option value="inline">内联</option>
                      <option value="path">路径</option>
                    </select>
                    <button
                      type="button"
                      className="btn-xs"
                      onClick={() => removeSkillItem(index)}
                      disabled={!editing}
                    >
                      删除
                    </button>
                  </div>
                  {itemDraft.kind === 'path' ? (
                    <input
                      value={itemDraft.path}
                      disabled={!editing}
                      onChange={(event) =>
                        updateSkillItem(index, { ...item, path: event.target.value })
                      }
                      placeholder="./skills/python/SKILL.md"
                    />
                  ) : (
                    <div className="agent-form-grid">
                      <input
                        value={itemDraft.name}
                        disabled={!editing}
                        onChange={(event) =>
                          updateSkillItem(index, { ...item, name: event.target.value })
                        }
                        placeholder="Skill 名称"
                      />
                      <input
                        value={itemDraft.description}
                        disabled={!editing}
                        onChange={(event) =>
                          updateSkillItem(index, { ...item, description: event.target.value })
                        }
                        placeholder="说明"
                      />
                      <textarea
                        rows={3}
                        value={itemDraft.instructions}
                        disabled={!editing}
                        onChange={(event) =>
                          updateSkillItem(index, { ...item, instructions: event.target.value })
                        }
                        placeholder="内联指令"
                      />
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>
    )
  }

  const renderMcpEditor = () => {
    if (!draft) return null
    return (
      <div className="agent-config-editor">
        <div className="agent-inline-actions">
          <button type="button" onClick={addMcpServer} disabled={!editing}>
            添加 MCP Server
          </button>
          <button
            type="button"
            className="btn-danger"
            onClick={() => updateDraft({ mcp_servers: [] })}
            disabled={!editing || draft.mcp_servers.length === 0}
          >
            清空
          </button>
        </div>

        <div className="agent-import-box">
          <div className="agent-import-box__controls">
            <select
              value={mcpImportFormat}
              disabled={!editing || importingMcp}
              onChange={(event) => setMcpImportFormat(event.target.value as 'auto' | 'json' | 'yaml')}
            >
              <option value="auto">自动识别</option>
              <option value="json">JSON</option>
              <option value="yaml">YAML</option>
            </select>
            <select
              value={mcpImportMode}
              disabled={!editing || importingMcp}
              onChange={(event) => setMcpImportMode(event.target.value as 'merge' | 'replace')}
            >
              <option value="merge">合并</option>
              <option value="replace">替换</option>
            </select>
            <button
              type="button"
              onClick={handleImportMcp}
              disabled={!editing || importingMcp || !mcpImportText.trim()}
            >
              {importingMcp ? '解析中...' : '解析并应用'}
            </button>
          </div>
          <textarea
            rows={4}
            value={mcpImportText}
            disabled={!editing || importingMcp}
            onChange={(event) => setMcpImportText(event.target.value)}
            placeholder="粘贴 Claude Desktop、Cursor、mcp.json 或 .mcp 配置"
          />
        </div>

        <div className="agent-edit-list">
          {draft.mcp_servers.length === 0 ? (
            <div className="empty-state" style={{ padding: 16 }}>
              <span>未挂载 MCP Server</span>
            </div>
          ) : (
            draft.mcp_servers.map((server, index) => {
              const envText =
                (server as EditableMcpServer)._envText ??
                JSON.stringify(server.env || {}, null, 2)
              return (
                <div className="agent-edit-row" key={`${server.name}-${index}`}>
                  <div className="agent-edit-row__top">
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={server.enabled !== false}
                        disabled={!editing}
                        onChange={(event) =>
                          updateMcpServer(index, { enabled: event.target.checked })
                        }
                      />
                      <span>启用</span>
                    </label>
                    <button
                      type="button"
                      className="btn-xs"
                      onClick={() => removeMcpServer(index)}
                      disabled={!editing}
                    >
                      删除
                    </button>
                  </div>
                  <div className="agent-form-grid">
                    <input
                      value={server.name}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { name: event.target.value })}
                      placeholder="名称"
                    />
                    <input
                      value={server.transport || 'stdio'}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { transport: event.target.value })}
                      placeholder="stdio"
                    />
                    <input
                      value={server.command || ''}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { command: event.target.value })}
                      placeholder="命令，例如 npx"
                    />
                    <input
                      value={server.url || ''}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { url: event.target.value })}
                      placeholder="远程 URL，可留空"
                    />
                    <input
                      value={server.cwd || ''}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { cwd: event.target.value })}
                      placeholder="工作目录"
                    />
                    <textarea
                      rows={3}
                      value={(server.args || []).join('\n')}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { args: splitLines(event.target.value) })}
                      placeholder="每行一个参数"
                    />
                    <textarea
                      rows={3}
                      value={envText}
                      disabled={!editing}
                      onChange={(event) => {
                        const text = event.target.value
                        updateMcpServer(index, { _envText: text })
                        try {
                          const parsed = JSON.parse(text || '{}')
                          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                            throw new Error()
                          }
                          updateMcpServer(index, { env: parsed as Record<string, string>, _envText: text })
                          setError('')
                        } catch {
                          setError('环境变量必须是 JSON 对象')
                        }
                      }}
                      placeholder='{"TOKEN":"${MCP_TOKEN}"}'
                    />
                    <textarea
                      rows={2}
                      value={server.description || ''}
                      disabled={!editing}
                      onChange={(event) => updateMcpServer(index, { description: event.target.value })}
                      placeholder="说明"
                    />
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">智能体</h1>
          <div className="page__subtitle">
            以智能体为单位管理模型、工具、Skills 与 MCP 挂载。
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
                    <button type="button" className="btn-primary" onClick={handleSave} disabled={saving}>
                      {saving ? '保存中...' : '保存'}
                    </button>
                  </>
                )}
              </div>
              <dl className="agent-detail__hero-meta">
                <div>
                  <dt>角色描述</dt>
                  <dd>{detail.description || '-'}</dd>
                </div>
                <div>
                  <dt>输出格式</dt>
                  <dd>{detail.output_format || 'text'}</dd>
                </div>
                <div>
                  <dt>最大迭代</dt>
                  <dd>{detail.max_iterations ?? '-'}</dd>
                </div>
                <div>
                  <dt>模型</dt>
                  <dd>
                    {detail.llm?.model || detail.model || '继承全局'}
                    {detail.llm?.source === 'agent_config' ? '（独立）' : ''}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">基础信息</span>
              </header>
              <div className="agent-section__body">
                <div className="agent-form-grid">
                  <label className="agent-form-field">
                    <span>角色描述</span>
                    <input
                      type="text"
                      value={draft.description}
                      disabled={!editing}
                      onChange={(event) => updateDraft({ description: event.target.value })}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>输出格式</span>
                    <Select
                      value={draft.output_format}
                      disabled={!editing}
                      onChange={(value) => updateDraft({ output_format: value as 'text' | 'json' })}
                      options={[
                        { value: 'text', label: 'text' },
                        { value: 'json', label: 'json' },
                      ]}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>最大迭代次数</span>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={draft.max_iterations}
                      disabled={!editing}
                      onChange={(event) => updateDraft({ max_iterations: Number(event.target.value) || 1 })}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>默认工作区</span>
                    <Select
                      value={draft.default_workspace_id}
                      disabled={!editing}
                      onChange={(value) => updateDraft({ default_workspace_id: value })}
                      options={[
                        { value: '', label: '未指定', description: '运行时由用户选择' },
                        ...state.workspaces.map((workspace) => ({
                          value: workspace.id,
                          label: workspace.name,
                          description: workspace.metadata?.description || '受管理工作区',
                        })),
                      ]}
                    />
                  </label>
                </div>
              </div>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">模型配置</span>
                <span className="text-muted">
                  当前来源：{detail.llm?.source === 'agent_config' ? 'Agent 独立配置' : '继承全局配置'}
                </span>
              </header>
              <div className="agent-section__body">
                <div className="agent-form-grid">
                  <label className="agent-form-field">
                    <span>Provider</span>
                    <Select
                      value={draft.llm_provider}
                      disabled={!editing}
                      onChange={(value) => updateDraft({ llm_provider: value })}
                      options={[
                        { value: '', label: '继承全局' },
                        { value: 'openai', label: 'OpenAI / 兼容接口' },
                        { value: 'anthropic', label: 'Anthropic' },
                      ]}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>模型</span>
                    <input
                      type="text"
                      value={draft.llm_model}
                      disabled={!editing}
                      placeholder={detail.llm?.source === 'global_default' ? detail.llm.model || '' : '继承全局模型'}
                      onChange={(event) => updateDraft({ llm_model: event.target.value })}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>Base URL</span>
                    <input
                      type="text"
                      value={draft.llm_base_url}
                      disabled={!editing}
                      placeholder="留空则继承全局地址"
                      onChange={(event) => updateDraft({ llm_base_url: event.target.value })}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>API Key</span>
                    <input
                      type="password"
                      value={draft.llm_api_key}
                      disabled={!editing}
                      placeholder={detail.llm?.api_key_set ? '已配置，留空不变' : '留空则继承全局密钥'}
                      onChange={(event) => updateDraft({ llm_api_key: event.target.value })}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>Temperature</span>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.1}
                      value={draft.llm_temperature}
                      disabled={!editing}
                      placeholder="继承"
                      onChange={(event) => updateDraft({ llm_temperature: event.target.value })}
                    />
                  </label>
                  <label className="agent-form-field">
                    <span>Max Tokens</span>
                    <input
                      type="number"
                      min={1}
                      value={draft.llm_max_tokens}
                      disabled={!editing}
                      placeholder="继承"
                      onChange={(event) => updateDraft({ llm_max_tokens: event.target.value })}
                    />
                  </label>
                </div>
              </div>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">System Prompt</span>
                <span className="text-muted" style={{ fontSize: 11.5 }}>
                  运行时会追加 Skills / MCP 摘要。
                </span>
              </header>
              <div className="agent-section__body">
                {editing ? (
                  <textarea
                    rows={10}
                    value={draft.system_prompt}
                    onChange={(event) => updateDraft({ system_prompt: event.target.value })}
                    style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}
                  />
                ) : (
                  <div className="agent-system-prompt-block">
                    {draft.system_prompt || '- 未配置 -'}
                  </div>
                )}
              </div>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">Tools 挂载</span>
                <span className="text-muted">
                  已选 {draft.tools.length} / {capabilities.length}
                </span>
              </header>
              <div className="agent-section__body">{renderToolsPicker()}</div>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">Skills 挂载</span>
                <span className="text-muted">{draft.skills?.items?.length || 0} 项</span>
              </header>
              <div className="agent-section__body">{renderSkillsEditor()}</div>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">MCP 挂载</span>
                <span className="text-muted">{draft.mcp_servers.length} 个 Server</span>
              </header>
              <div className="agent-section__body">{renderMcpEditor()}</div>
            </section>

            <section className="agent-section">
              <header className="agent-section__header">
                <span className="agent-section__title">默认人格</span>
                <span className="text-muted">在人格页统一管理</span>
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
                    <div style={{ marginTop: 6, fontSize: 12.5, color: 'var(--color-text-secondary)' }}>
                      {personaForAgent.description || '-'}
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
