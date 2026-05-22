import { useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { AgentInfo, AgentMCPServerConfig } from '../types'
import {
  emptyMcpServerDraft,
  mcpDraftToServer,
  mcpServerToDraft,
  type McpServerDraft,
} from './skillMcpFormLogic'
import './McpPanel.css'

interface McpEntry {
  key: string
  name: string
  command?: string
  args: string[]
  transport?: string
  description?: string
  envKeys: string[]
  cwd?: string
  agents: Array<{ agent: string; enabled: boolean }>
}

function configKey(server: AgentMCPServerConfig) {
  return `${server.name}::${server.command || ''}::${(server.args || []).join(' ')}`
}

export function McpPanel() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedAgent, setSelectedAgent] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [draft, setDraft] = useState<McpServerDraft>(emptyMcpServerDraft())

  const selectedAgentInfo = useMemo(
    () => agents.find((agent) => agent.name === selectedAgent) || null,
    [agents, selectedAgent]
  )

  const selectedServers = selectedAgentInfo?.mcp_servers || []

  const syncDraft = (
    agent: AgentInfo | null,
    index: number,
    options: { newServer?: boolean } = {}
  ) => {
    const servers = agent?.mcp_servers || []
    if (options.newServer || !servers[index]) {
      setSelectedIndex(servers.length)
      setDraft(emptyMcpServerDraft())
      return
    }
    setSelectedIndex(index)
    setDraft(mcpServerToDraft(servers[index]))
  }

  const loadAgents = async (preferredAgent?: string, preferredIndex = 0) => {
    setLoading(true)
    setError('')
    const res = await api.listAgents()
    setLoading(false)
    if (res.status !== 'ok' || !Array.isArray(res.data)) {
      setError(res.message || '加载智能体失败。')
      return
    }

    setAgents(res.data)
    const nextName = preferredAgent || selectedAgent || res.data[0]?.name || ''
    const nextAgent = res.data.find((agent) => agent.name === nextName) || null
    if (nextAgent) {
      setSelectedAgent(nextAgent.name)
      syncDraft(nextAgent, preferredIndex)
    }
  }

  useEffect(() => {
    loadAgents()
  }, [])

  const aggregated = useMemo<McpEntry[]>(() => {
    const map = new Map<string, McpEntry>()
    for (const agent of agents) {
      for (const server of agent.mcp_servers || []) {
        const key = configKey(server)
        const enabled = server.enabled !== false
        const existing = map.get(key)
        if (existing) {
          existing.agents.push({ agent: agent.name, enabled })
        } else {
          map.set(key, {
            key,
            name: server.name,
            command: server.command,
            args: server.args || [],
            transport: server.transport,
            description: server.description,
            envKeys: Object.keys(server.env || {}),
            cwd: server.cwd,
            agents: [{ agent: agent.name, enabled }],
          })
        }
      }
    }
    return Array.from(map.values()).sort((a, b) =>
      a.name.localeCompare(b.name, 'zh-CN')
    )
  }, [agents])

  const stats = useMemo(() => {
    let totalConfigs = 0
    let enabledConfigs = 0
    let agentsWithMcp = 0
    for (const agent of agents) {
      const list = agent.mcp_servers || []
      if (list.length > 0) agentsWithMcp += 1
      totalConfigs += list.length
      for (const server of list) {
        if (server.enabled !== false) enabledConfigs += 1
      }
    }
    return {
      totalConfigs,
      enabledConfigs,
      agentsWithMcp,
      uniqueServers: aggregated.length,
    }
  }, [agents, aggregated])

  const chooseAgent = (name: string) => {
    const agent = agents.find((item) => item.name === name) || null
    setSelectedAgent(name)
    syncDraft(agent, 0)
    setNotice('')
    setError('')
  }

  const chooseServer = (indexValue: string) => {
    const index = Number(indexValue)
    syncDraft(selectedAgentInfo, index, {
      newServer: index >= selectedServers.length,
    })
    setNotice('')
    setError('')
  }

  const saveDraft = async () => {
    if (!selectedAgentInfo) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const server = mcpDraftToServer(draft)
      const nextServers = [...selectedServers]
      if (selectedIndex >= selectedServers.length) {
        nextServers.push(server)
      } else {
        nextServers[selectedIndex] = server
      }
      const res = await api.updateAgent(selectedAgentInfo.name, {
        mcp_servers: nextServers,
      })
      if (res.status !== 'ok') {
        throw new Error(res.message || '保存 MCP 配置失败。')
      }
      setNotice('MCP Server 配置已保存。')
      await loadAgents(selectedAgentInfo.name, Math.min(selectedIndex, nextServers.length - 1))
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 MCP 配置失败。')
    } finally {
      setSaving(false)
    }
  }

  const removeServer = async () => {
    if (!selectedAgentInfo || selectedIndex >= selectedServers.length) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const nextServers = selectedServers.filter((_, index) => index !== selectedIndex)
      const res = await api.updateAgent(selectedAgentInfo.name, {
        mcp_servers: nextServers,
      })
      if (res.status !== 'ok') {
        throw new Error(res.message || '删除 MCP 配置失败。')
      }
      setNotice('已删除该 MCP Server 配置。')
      await loadAgents(selectedAgentInfo.name, Math.max(0, selectedIndex - 1))
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除 MCP 配置失败。')
    } finally {
      setSaving(false)
    }
  }

  const clearServers = async () => {
    if (!selectedAgentInfo) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const res = await api.updateAgent(selectedAgentInfo.name, {
        mcp_servers: [],
      })
      if (res.status !== 'ok') {
        throw new Error(res.message || '清空 MCP 配置失败。')
      }
      setNotice('已清空该智能体的 MCP Server 配置。')
      await loadAgents(selectedAgentInfo.name, 0)
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空 MCP 配置失败。')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">MCP</h1>
          <div className="page__subtitle">
            按智能体管理 Model Context Protocol Server 配置。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" onClick={() => loadAgents()} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
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
      {notice && (
        <div className="alert alert--success">
          <span style={{ flex: 1 }}>{notice}</span>
          <button className="btn-xs" onClick={() => setNotice('')}>
            关闭
          </button>
        </div>
      )}

      <div className="mcp-stats">
        <div className="mcp-stats__card">
          <div className="mcp-stats__label">独立 Server 数</div>
          <div className="mcp-stats__value">{stats.uniqueServers}</div>
        </div>
        <div className="mcp-stats__card">
          <div className="mcp-stats__label">挂载次数</div>
          <div className="mcp-stats__value">{stats.totalConfigs}</div>
        </div>
        <div className="mcp-stats__card">
          <div className="mcp-stats__label">启用中</div>
          <div className="mcp-stats__value">
            {stats.enabledConfigs}
            <span> / {stats.totalConfigs || 0}</span>
          </div>
        </div>
        <div className="mcp-stats__card">
          <div className="mcp-stats__label">使用中的智能体</div>
          <div className="mcp-stats__value">
            {stats.agentsWithMcp} <span>/ {agents.length}</span>
          </div>
        </div>
      </div>

      <section className="console-card">
        <header className="console-card__header">
          <span className="console-card__title">按 Agent 编辑</span>
          <span className="text-muted">
            环境变量值可能已由后端脱敏，请优先填写变量引用。
          </span>
        </header>
        <div className="console-card__body mcp-editor">
          <div className="mcp-editor__grid">
            <label className="form-field">
              <span>智能体</span>
              <select
                value={selectedAgent}
                onChange={(event) => chooseAgent(event.target.value)}
              >
                {agents.map((agent) => (
                  <option key={agent.name} value={agent.name}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>MCP Server</span>
              <select
                value={selectedIndex}
                onChange={(event) => chooseServer(event.target.value)}
              >
                {selectedServers.map((server, index) => (
                  <option key={`${server.name}-${index}`} value={index}>
                    {server.name || `未命名 Server ${index + 1}`}
                  </option>
                ))}
                <option value={selectedServers.length}>新增 Server</option>
              </select>
            </label>
          </div>

          <div className="mcp-editor__grid">
            <label className="form-field">
              <span>名称</span>
              <input
                value={draft.name}
                onChange={(event) =>
                  setDraft({ ...draft, name: event.target.value })
                }
              />
            </label>
            <label className="form-field">
              <span>传输方式</span>
              <input
                value={draft.transport}
                onChange={(event) =>
                  setDraft({ ...draft, transport: event.target.value })
                }
                placeholder="stdio"
              />
            </label>
          </div>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) =>
                setDraft({ ...draft, enabled: event.target.checked })
              }
            />
            <span>启用该 MCP Server</span>
          </label>

          <div className="mcp-editor__grid">
            <label className="form-field">
              <span>命令</span>
              <input
                value={draft.command}
                onChange={(event) =>
                  setDraft({ ...draft, command: event.target.value })
                }
                placeholder="npx"
              />
            </label>
            <label className="form-field">
              <span>工作目录</span>
              <input
                value={draft.cwd}
                onChange={(event) =>
                  setDraft({ ...draft, cwd: event.target.value })
                }
                placeholder="."
              />
            </label>
          </div>

          <label className="form-field">
            <span>参数</span>
            <textarea
              rows={4}
              value={draft.argsText}
              onChange={(event) =>
                setDraft({ ...draft, argsText: event.target.value })
              }
              placeholder="每行一个参数"
            />
          </label>

          <label className="form-field">
            <span>环境变量 JSON</span>
            <textarea
              rows={5}
              className="text-mono"
              value={draft.envText}
              onChange={(event) =>
                setDraft({ ...draft, envText: event.target.value })
              }
              placeholder='{"TOKEN":"${MCP_TOKEN}"}'
            />
          </label>

          <label className="form-field">
            <span>说明</span>
            <textarea
              rows={3}
              value={draft.description}
              onChange={(event) =>
                setDraft({ ...draft, description: event.target.value })
              }
            />
          </label>

          <div className="editor-actions">
            <button
              type="button"
              className="btn-primary"
              onClick={saveDraft}
              disabled={!selectedAgentInfo || saving}
            >
              {saving ? '保存中...' : '保存配置'}
            </button>
            <button
              type="button"
              onClick={() => syncDraft(selectedAgentInfo, selectedServers.length, { newServer: true })}
              disabled={saving}
            >
              新增 Server
            </button>
            <button
              type="button"
              onClick={removeServer}
              disabled={saving || selectedIndex >= selectedServers.length}
            >
              删除当前 Server
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={clearServers}
              disabled={!selectedAgentInfo || saving}
            >
              清空该 Agent 配置
            </button>
          </div>
        </div>
      </section>

      <div className="mcp-shell">
        <aside className="mcp-list">
          <div className="mcp-list__header">
            <span style={{ fontWeight: 600 }}>Server 列表</span>
            <span className="text-muted">{aggregated.length}</span>
          </div>
          <div className="mcp-list__items">
            {aggregated.length === 0 ? (
              <div className="empty-state" style={{ padding: 24 }}>
                <strong>尚未配置 MCP Server</strong>
                <span>请选择智能体后在上方表单添加配置。</span>
              </div>
            ) : (
              aggregated.map((entry) => {
                const enabledOn = entry.agents.filter((a) => a.enabled).length
                return (
                  <div className="mcp-row" key={entry.key}>
                    <div className="mcp-row__title">
                      <strong>{entry.name}</strong>
                      {entry.transport && (
                        <span className="pill">{entry.transport}</span>
                      )}
                    </div>
                    <div className="mcp-row__meta text-mono">
                      {entry.command || '-'}
                      {entry.args.length > 0 ? ` ${entry.args.join(' ')}` : ''}
                    </div>
                    <div className="mcp-row__badges">
                      <span
                        className={`pill ${
                          enabledOn === entry.agents.length
                            ? 'pill--success'
                            : enabledOn === 0
                            ? 'pill--warning'
                            : 'pill--info'
                        }`}
                      >
                        启用 {enabledOn}/{entry.agents.length}
                      </span>
                      <span className="text-muted" style={{ fontSize: 11 }}>
                        挂载到 {entry.agents.length} 个智能体
                      </span>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </aside>

        <section className="mcp-detail">
          <section className="console-card">
            <header className="console-card__header">
              <span className="console-card__title">当前 Agent 配置</span>
              <span className="text-muted">
                {selectedServers.length} 个 Server
              </span>
            </header>
            <div className="console-card__body--flush">
              {selectedServers.length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span>该智能体尚未配置 MCP Server。</span>
                </div>
              ) : (
                selectedServers.map((server, index) => (
                  <div className="row" key={`${server.name}-${index}`}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 500 }}>{server.name}</div>
                      <div className="text-mono" style={{ fontSize: 11.5 }}>
                        {server.command || '-'}
                        {server.args?.length ? ` ${server.args.join(' ')}` : ''}
                      </div>
                    </div>
                    <span
                      className={`pill ${
                        server.enabled !== false ? 'pill--success' : 'pill--warning'
                      }`}
                    >
                      {server.enabled !== false ? '启用' : '关闭'}
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        </section>
      </div>
    </div>
  )
}
