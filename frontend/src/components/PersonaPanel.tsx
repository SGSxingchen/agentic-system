import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { Persona, PersonaBindings, PersonaProposal, PersonaVersion } from '../types'
import './PersonaPanel.css'

const STATUS_LABEL: Record<string, string> = {
  active: '已激活',
  draft: '草稿',
  archived: '已归档',
}

const PROPOSAL_STATUS_LABEL: Record<string, string> = {
  pending: '历史归档',
  approved: '已通过',
  rejected: '已拒绝',
}

function statusPill(status: string) {
  switch (status) {
    case 'active':
      return 'pill pill--success'
    case 'draft':
      return 'pill pill--warning'
    case 'archived':
      return 'pill'
    default:
      return 'pill'
  }
}

function proposalStatusPill(status: string) {
  switch (status) {
    case 'approved':
      return 'pill pill--success'
    case 'rejected':
      return 'pill pill--danger'
    case 'pending':
    default:
      return 'pill pill--warning'
  }
}

function formatDateTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

interface DraftPersona {
  name: string
  description: string
  persona_prompt: string
  permission_boundary: string
  style_rules: string
  behavior_rules: string
}

function toDraft(persona: Persona): DraftPersona {
  return {
    name: persona.name,
    description: persona.description,
    persona_prompt: persona.persona_prompt,
    permission_boundary: persona.permission_boundary,
    style_rules: (persona.style_rules || []).join('\n'),
    behavior_rules: (persona.behavior_rules || []).join('\n'),
  }
}

export function PersonaPanel() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [bindings, setBindings] = useState<PersonaBindings | null>(null)
  const [proposals, setProposals] = useState<PersonaProposal[]>([])
  const [versions, setVersions] = useState<PersonaVersion[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<DraftPersona | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)

  const flashNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 2400)
  }

  const loadPersonas = useCallback(async () => {
    const [pRes, bRes] = await Promise.all([
      api.listPersonas(includeArchived),
      api.getAgentPersonaBindings(),
    ])
    if (pRes.status === 'ok' && Array.isArray(pRes.data)) {
      const list = pRes.data
      setPersonas(list)
      setSelectedId((current) => current || list[0]?.id || null)
    } else {
      setError(pRes.message || '加载人格失败')
    }
    if (bRes.status === 'ok' && bRes.data) setBindings(bRes.data)
  }, [includeArchived])

  useEffect(() => {
    loadPersonas()
  }, [loadPersonas])

  useEffect(() => {
    api.listPersonaProposals('pending').then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) setProposals(res.data)
    })
  }, [])

  const selectedPersona = useMemo(
    () => personas.find((p) => p.id === selectedId) || null,
    [personas, selectedId]
  )

  useEffect(() => {
    if (!selectedPersona) {
      setDraft(null)
      setVersions([])
      return
    }
    setDraft(toDraft(selectedPersona))
    setEditing(false)
    api.listPersonaVersions(selectedPersona.id).then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) setVersions(res.data)
    })
  }, [selectedPersona])

  const handleSave = async () => {
    if (!selectedPersona || !draft) return
    setSaving(true)
    const payload: Partial<Persona> = {
      name: draft.name,
      description: draft.description,
      persona_prompt: draft.persona_prompt,
      permission_boundary: draft.permission_boundary,
      style_rules: draft.style_rules.split('\n').map((s) => s.trim()).filter(Boolean),
      behavior_rules: draft.behavior_rules
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
    }
    const res = await api.updatePersona(selectedPersona.id, payload)
    setSaving(false)
    if (res.status === 'ok') {
      flashNotice('已保存人格')
      setEditing(false)
      await loadPersonas()
    } else {
      setError(res.message || '保存失败')
    }
  }

  const handleArchiveToggle = async () => {
    if (!selectedPersona) return
    if (selectedPersona.status === 'archived') {
      const res = await api.restorePersona(selectedPersona.id)
      if (res.status === 'ok') {
        flashNotice('已恢复')
        await loadPersonas()
      } else {
        setError(res.message || '操作失败')
      }
    } else {
      const ok = window.confirm('确认归档该人格？归档后将不会被新会话使用。')
      if (!ok) return
      const res = await api.archivePersona(selectedPersona.id)
      if (res.status === 'ok') {
        flashNotice('已归档')
        await loadPersonas()
      } else {
        setError(res.message || '操作失败')
      }
    }
  }

  const handleApproveProposal = async (proposalId: string) => {
    const res = await api.approvePersonaProposal(proposalId, 'admin', '管理员审核通过')
    if (res.status === 'ok') {
      flashNotice('审核已通过')
      const refreshed = await api.listPersonaProposals('pending')
      if (refreshed.status === 'ok' && Array.isArray(refreshed.data)) {
        setProposals(refreshed.data)
      }
      await loadPersonas()
    } else {
      setError(res.message || '操作失败')
    }
  }

  const handleRejectProposal = async (proposalId: string) => {
    const res = await api.rejectPersonaProposal(proposalId, 'admin', '管理员拒绝')
    if (res.status === 'ok') {
      flashNotice('已拒绝')
      const refreshed = await api.listPersonaProposals('pending')
      if (refreshed.status === 'ok' && Array.isArray(refreshed.data)) {
        setProposals(refreshed.data)
      }
    } else {
      setError(res.message || '操作失败')
    }
  }

  const handleRollback = async (version: number) => {
    if (!selectedPersona) return
    const ok = window.confirm(`回滚到版本 v${version}？`)
    if (!ok) return
    const res = await api.rollbackPersona(selectedPersona.id, version, 'admin')
    if (res.status === 'ok') {
      flashNotice(`已回滚到 v${version}`)
      await loadPersonas()
    } else {
      setError(res.message || '回滚失败')
    }
  }

  // === bindings derived ===
  const agentBindings = useMemo(() => {
    if (!bindings || !selectedPersona) return [] as string[]
    return Object.entries(bindings.agents || {})
      .filter(([, personaId]) => personaId === selectedPersona.id)
      .map(([agent]) => agent)
  }, [bindings, selectedPersona])

  const sessionBindings = useMemo(() => {
    if (!bindings || !selectedPersona) return [] as string[]
    return Object.entries(bindings.sessions || {})
      .filter(([, personaId]) => personaId === selectedPersona.id)
      .map(([sessionId]) => sessionId)
  }, [bindings, selectedPersona])

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">人格</h1>
          <div className="page__subtitle">
            人格定义角色、风格与权限边界，按 Agent 或会话绑定。
            {bindings?.precedence && bindings.precedence.length > 0 && (
              <>
                {' '}
                优先级：{bindings.precedence.join(' → ')}
              </>
            )}
          </div>
        </div>
        <div className="page__actions">
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 12.5,
              color: 'var(--color-text-secondary)',
            }}
          >
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            <span>包含已归档</span>
          </label>
          <button type="button" onClick={loadPersonas}>
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

      {proposals.length > 0 && (
        <section className="console-card">
          <header className="console-card__header">
            <span className="console-card__title">人格补丁建议（历史归档）</span>
            <span className="text-muted">{proposals.length} 条</span>
          </header>
          <div style={{ padding: '8px 12px 0 12px', fontSize: 12, color: 'var(--color-text-muted)' }}>
            A10 之后，人格变更通过 update_persona 调用即生效，不再走两段式审批。下方仅展示历史归档的 pending 提案数据。
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12 }}>
            {proposals.map((proposal) => (
              <div className="persona-proposal" key={proposal.id}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <div>
                    <strong>{proposal.summary || '人格变更建议'}</strong>
                    <div style={{ color: 'var(--color-text-muted)', fontSize: 11.5 }}>
                      来源 {proposal.source} · 基于 v{proposal.base_version} ·{' '}
                      {formatDateTime(proposal.created_at)}
                    </div>
                  </div>
                  <span className={proposalStatusPill(proposal.status)}>
                    {PROPOSAL_STATUS_LABEL[proposal.status] || proposal.status}
                  </span>
                </div>
                {proposal.proposal_text && (
                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
                    {proposal.proposal_text}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn-sm"
                    onClick={() => handleRejectProposal(proposal.id)}
                  >
                    拒绝
                  </button>
                  <button
                    type="button"
                    className="btn-primary btn-sm"
                    onClick={() => handleApproveProposal(proposal.id)}
                  >
                    通过
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="persona-shell">
        <aside className="persona-list">
          <div className="persona-list__header">
            <span style={{ fontWeight: 600 }}>人格列表</span>
            <span className="text-muted">{personas.length} 个</span>
          </div>
          <div className="persona-list__items">
            {personas.length === 0 ? (
              <div className="empty-state">
                <span>暂无人格</span>
              </div>
            ) : (
              personas.map((persona) => (
                <button
                  key={persona.id}
                  type="button"
                  className={`persona-row ${
                    selectedId === persona.id ? 'persona-row--active' : ''
                  }`}
                  onClick={() => setSelectedId(persona.id)}
                >
                  <span className="persona-row__name">{persona.name}</span>
                  <span className={statusPill(persona.status)}>
                    {STATUS_LABEL[persona.status] || persona.status}
                  </span>
                  <span className="persona-row__sub">
                    v{persona.version} · {formatDateTime(persona.updated_at)}
                  </span>
                </button>
              ))
            )}
          </div>
        </aside>

        {selectedPersona && draft ? (
          <div className="persona-detail">
            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">{selectedPersona.name}</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  {!editing ? (
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={() => setEditing(true)}
                    >
                      编辑
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(false)
                          setDraft(toDraft(selectedPersona))
                        }}
                      >
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
                  <button
                    type="button"
                    className={
                      selectedPersona.status === 'archived' ? '' : 'btn-danger'
                    }
                    onClick={handleArchiveToggle}
                  >
                    {selectedPersona.status === 'archived' ? '恢复' : '归档'}
                  </button>
                </div>
              </header>
              <div className="console-card__body">
                <dl className="persona-meta-grid">
                  <div>
                    <dt>状态</dt>
                    <dd>
                      <span className={statusPill(selectedPersona.status)}>
                        {STATUS_LABEL[selectedPersona.status]}
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt>当前版本</dt>
                    <dd>v{selectedPersona.version}</dd>
                  </div>
                  <div>
                    <dt>创建时间</dt>
                    <dd>{formatDateTime(selectedPersona.created_at)}</dd>
                  </div>
                  <div>
                    <dt>更新时间</dt>
                    <dd>{formatDateTime(selectedPersona.updated_at)}</dd>
                  </div>
                </dl>
              </div>
            </section>

            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">基础信息</span>
              </header>
              <div className="console-card__body">
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '10px 16px',
                  }}
                >
                  <div>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      名称
                    </label>
                    <input
                      type="text"
                      value={draft.name}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({ ...draft, name: event.target.value })
                      }
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      权限边界
                    </label>
                    <input
                      type="text"
                      value={draft.permission_boundary}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          permission_boundary: event.target.value,
                        })
                      }
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div style={{ gridColumn: '1 / -1' }}>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      简述
                    </label>
                    <input
                      type="text"
                      value={draft.description}
                      disabled={!editing}
                      onChange={(event) =>
                        setDraft({ ...draft, description: event.target.value })
                      }
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>
              </div>
            </section>

            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">人格 Prompt</span>
              </header>
              <div className="console-card__body">
                {editing ? (
                  <textarea
                    rows={8}
                    value={draft.persona_prompt}
                    onChange={(event) =>
                      setDraft({ ...draft, persona_prompt: event.target.value })
                    }
                    style={{
                      width: '100%',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12.5,
                    }}
                  />
                ) : (
                  <div className="persona-prompt-block">
                    {draft.persona_prompt || '— 未配置 —'}
                  </div>
                )}
              </div>
            </section>

            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">风格与行为规则</span>
                <span className="text-muted" style={{ fontSize: 11.5 }}>
                  每行一条
                </span>
              </header>
              <div className="console-card__body">
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 16,
                  }}
                >
                  <div>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      风格
                    </label>
                    {editing ? (
                      <textarea
                        rows={8}
                        value={draft.style_rules}
                        onChange={(event) =>
                          setDraft({ ...draft, style_rules: event.target.value })
                        }
                        style={{
                          width: '100%',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 12.5,
                        }}
                      />
                    ) : (
                      <ul className="persona-rules">
                        {selectedPersona.style_rules?.length ? (
                          selectedPersona.style_rules.map((rule, idx) => (
                            <li key={idx}>{rule}</li>
                          ))
                        ) : (
                          <li className="text-muted">— 未配置 —</li>
                        )}
                      </ul>
                    )}
                  </div>
                  <div>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      行为
                    </label>
                    {editing ? (
                      <textarea
                        rows={8}
                        value={draft.behavior_rules}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            behavior_rules: event.target.value,
                          })
                        }
                        style={{
                          width: '100%',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 12.5,
                        }}
                      />
                    ) : (
                      <ul className="persona-rules">
                        {selectedPersona.behavior_rules?.length ? (
                          selectedPersona.behavior_rules.map((rule, idx) => (
                            <li key={idx}>{rule}</li>
                          ))
                        ) : (
                          <li className="text-muted">— 未配置 —</li>
                        )}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            </section>

            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">绑定关系</span>
              </header>
              <div className="console-card__body">
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 16,
                    fontSize: 12.5,
                  }}
                >
                  <div>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      绑定的智能体（{agentBindings.length}）
                    </label>
                    {agentBindings.length === 0 ? (
                      <div className="text-muted">未绑定到任何智能体</div>
                    ) : (
                      <ul className="persona-rules">
                        {agentBindings.map((agent) => (
                          <li key={agent}>{agent}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <label
                      style={{
                        fontSize: 11.5,
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      绑定的会话（{sessionBindings.length}）
                    </label>
                    {sessionBindings.length === 0 ? (
                      <div className="text-muted">未绑定会话</div>
                    ) : (
                      <ul className="persona-rules">
                        {sessionBindings.map((sessionId) => (
                          <li key={sessionId} className="text-mono" style={{ fontSize: 11.5 }}>
                            {sessionId}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            </section>

            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">版本历史</span>
                <span className="text-muted">{versions.length} 个版本</span>
              </header>
              {versions.length === 0 ? (
                <div className="empty-state">
                  <span>暂无版本记录</span>
                </div>
              ) : (
                versions.map((version) => (
                  <div className="persona-section__row" key={version.version}>
                    <div>
                      <strong>v{version.version}</strong>
                      <span
                        style={{
                          marginLeft: 8,
                          color: 'var(--color-text-muted)',
                          fontSize: 11.5,
                        }}
                      >
                        {formatDateTime(version.created_at)} ·{' '}
                        {version.reviewer || '—'}
                      </span>
                      {version.reason && (
                        <div
                          style={{
                            color: 'var(--color-text-muted)',
                            fontSize: 11.5,
                            marginTop: 2,
                          }}
                        >
                          {version.reason}
                        </div>
                      )}
                    </div>
                    {version.version !== selectedPersona.version && (
                      <button
                        type="button"
                        className="btn-sm"
                        onClick={() => handleRollback(version.version)}
                      >
                        回滚
                      </button>
                    )}
                  </div>
                ))
              )}
            </section>
          </div>
        ) : (
          <div className="persona-detail">
            <section className="console-card">
              <div className="console-card__body">
                <div className="empty-state">
                  <strong>请选择一个人格</strong>
                  <span>左侧列出已配置的人格。</span>
                </div>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
