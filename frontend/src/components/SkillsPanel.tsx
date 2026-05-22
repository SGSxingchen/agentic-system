import { useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { AgentInfo } from '../types'
import {
  buildSkillConfig,
  emptySkillDraft,
  skillConfigToDraft,
  type SkillDraft,
} from './skillMcpFormLogic'
import './SkillsPanel.css'

interface SkillEntry {
  key: string
  name: string
  description?: string
  source?: string
  agents: Array<{ agent: string; enabled: boolean }>
}

function pickString(record: Record<string, any> | undefined, ...keys: string[]) {
  if (!record) return undefined
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return undefined
}

function describeSkill(value: any) {
  if (!value || typeof value !== 'object') return null
  const name =
    pickString(value, 'name', 'id', 'slug', 'identifier') || 'unknown_skill'
  return {
    name,
    description: pickString(value, 'description', 'desc', 'summary'),
    source: pickString(value, 'path', 'source', 'directory', 'location'),
  }
}

export function SkillsPanel() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [selectedAgent, setSelectedAgent] = useState('')
  const [draft, setDraft] = useState<SkillDraft>(emptySkillDraft())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const loadAgents = async (preferredAgent?: string) => {
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
    const nextAgent = res.data.find((agent) => agent.name === nextName)
    if (nextAgent) {
      setSelectedAgent(nextAgent.name)
      setDraft(skillConfigToDraft(nextAgent.skills))
    }
  }

  useEffect(() => {
    loadAgents()
  }, [])

  const selected = useMemo(
    () => agents.find((agent) => agent.name === selectedAgent) || null,
    [agents, selectedAgent]
  )

  const stats = useMemo(() => {
    let totalMounts = 0
    let agentsWithSkills = 0
    let directories = new Set<string>()
    let enabledAgents = 0

    for (const agent of agents) {
      const items = agent.skills?.items || []
      if (items.length > 0) agentsWithSkills += 1
      if (agent.skills?.enabled) enabledAgents += 1
      totalMounts += items.length
      for (const dir of agent.skills?.directories || []) directories.add(dir)
    }

    return {
      totalMounts,
      agentsWithSkills,
      enabledAgents,
      directoryCount: directories.size,
    }
  }, [agents])

  const aggregated = useMemo<SkillEntry[]>(() => {
    const map = new Map<string, SkillEntry>()
    for (const agent of agents) {
      const disabled = new Set(agent.skills?.disabled || [])
      for (const raw of agent.skills?.items || []) {
        const item = describeSkill(raw)
        if (!item) continue
        const key = `${item.name}::${item.source || ''}`
        const existing = map.get(key)
        const binding = {
          agent: agent.name,
          enabled: agent.skills?.enabled !== false && !disabled.has(item.name),
        }
        if (existing) {
          existing.agents.push(binding)
        } else {
          map.set(key, { key, ...item, agents: [binding] })
        }
      }
    }
    return Array.from(map.values()).sort((a, b) =>
      a.name.localeCompare(b.name, 'zh-CN')
    )
  }, [agents])

  const chooseAgent = (name: string) => {
    const agent = agents.find((item) => item.name === name)
    setSelectedAgent(name)
    setDraft(skillConfigToDraft(agent?.skills))
    setNotice('')
    setError('')
  }

  const saveDraft = async (clear = false) => {
    if (!selected) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const skills = clear ? null : buildSkillConfig(draft)
      const res = await api.updateAgent(selected.name, { skills })
      if (res.status !== 'ok') {
        throw new Error(res.message || '保存 Skills 配置失败。')
      }
      setNotice(clear ? '已清空该智能体的 Skills 配置。' : 'Skills 配置已保存。')
      await loadAgents(selected.name)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 Skills 配置失败。')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">Skills</h1>
          <div className="page__subtitle">
            按智能体管理 Skills 加载配置，保存后由后端写入当前 Agent 配置。
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

      <div className="skills-stats">
        <div className="skills-stats__card">
          <div className="skills-stats__label">挂载总数</div>
          <div className="skills-stats__value">{stats.totalMounts}</div>
        </div>
        <div className="skills-stats__card">
          <div className="skills-stats__label">已配置智能体</div>
          <div className="skills-stats__value">
            {stats.agentsWithSkills} <span>/ {agents.length}</span>
          </div>
        </div>
        <div className="skills-stats__card">
          <div className="skills-stats__label">启用智能体</div>
          <div className="skills-stats__value">
            {stats.enabledAgents} <span>/ {agents.length}</span>
          </div>
        </div>
        <div className="skills-stats__card">
          <div className="skills-stats__label">配置目录</div>
          <div className="skills-stats__value">{stats.directoryCount}</div>
        </div>
      </div>

      <section className="console-card">
        <header className="console-card__header">
          <span className="console-card__title">按 Agent 编辑</span>
        </header>
        <div className="console-card__body skills-editor">
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

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) =>
                setDraft({ ...draft, enabled: event.target.checked })
              }
            />
            <span>启用该智能体的 Skills 加载</span>
          </label>

          <div className="skills-editor__grid">
            <label className="form-field">
              <span>加载策略</span>
              <input
                value={draft.strategy}
                onChange={(event) =>
                  setDraft({ ...draft, strategy: event.target.value })
                }
                placeholder="metadata_and_instructions"
              />
            </label>
            <label className="form-field">
              <span>禁用项</span>
              <textarea
                rows={4}
                value={draft.disabledText}
                onChange={(event) =>
                  setDraft({ ...draft, disabledText: event.target.value })
                }
                placeholder="每行一个 Skill 名称"
              />
            </label>
          </div>

          <label className="form-field">
            <span>Skill 目录</span>
            <textarea
              rows={4}
              value={draft.directoriesText}
              onChange={(event) =>
                setDraft({ ...draft, directoriesText: event.target.value })
              }
              placeholder="./skills&#10;../shared-skills"
            />
          </label>

          <label className="form-field">
            <span>Skill items JSON</span>
            <textarea
              rows={10}
              className="text-mono"
              value={draft.itemsText}
              onChange={(event) =>
                setDraft({ ...draft, itemsText: event.target.value })
              }
              placeholder='[{"name":"repo_style","description":"项目约定"}]'
            />
          </label>

          <div className="editor-actions">
            <button
              type="button"
              className="btn-primary"
              onClick={() => saveDraft()}
              disabled={!selected || saving}
            >
              {saving ? '保存中...' : '保存配置'}
            </button>
            <button
              type="button"
              onClick={() => setDraft(emptySkillDraft())}
              disabled={saving}
            >
              恢复为空配置
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={() => saveDraft(true)}
              disabled={!selected || saving}
            >
              清空配置
            </button>
          </div>
        </div>
      </section>

      <section className="console-card">
        <header className="console-card__header">
          <span className="console-card__title">已挂载 Skill 列表</span>
          <span className="text-muted">{aggregated.length} 项</span>
        </header>
        <div className="console-card__body--flush">
          {aggregated.length === 0 ? (
            <div className="empty-state" style={{ padding: 32 }}>
              <strong>暂无 Skill 挂载</strong>
              <span>请选择智能体后在上方表单添加配置。</span>
            </div>
          ) : (
            <div className="skill-table">
              <div className="skill-table__head">
                <span>名称</span>
                <span>来源</span>
                <span>挂载到</span>
              </div>
              {aggregated.map((entry) => (
                <div className="skill-table__row" key={entry.key}>
                  <div className="skill-table__name">
                    <strong>{entry.name}</strong>
                    {entry.description && (
                      <span className="skill-table__desc">
                        {entry.description}
                      </span>
                    )}
                  </div>
                  <div className="skill-table__source text-mono">
                    {entry.source || '-'}
                  </div>
                  <div className="skill-table__agents">
                    {entry.agents.map((binding) => (
                      <span
                        key={binding.agent}
                        className={`pill ${
                          binding.enabled ? 'pill--success' : 'pill--warning'
                        }`}
                        title={binding.enabled ? '已启用' : '未启用'}
                      >
                        {binding.agent}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
