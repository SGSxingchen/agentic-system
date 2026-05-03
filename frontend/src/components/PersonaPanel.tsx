import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Persona, PersonaBindings, PersonaProposal, PersonaVersion } from '../types'
import {
  approvePersonaProposal,
  archivePersona,
  bindAgentPersona,
  bindSessionPersona,
  createPersona,
  createPersonaProposal,
  getAgents,
  getPersonaBindings,
  listPersonaProposals,
  listPersonas,
  listPersonaVersions,
  rejectPersonaProposal,
  restorePersona,
  rollbackPersona,
  updatePersona,
} from '../api/client'
import './PersonaPanel.css'

const BASE_ID = 'base-assistant'

function linesToList(value: string): string[] {
  return value.split('\n').map((line) => line.replace(/^[-•]\s*/, '').trim()).filter(Boolean)
}

function listToText(value?: string[]): string {
  return (value || []).join('\n')
}

function emptyDraft(): Persona {
  const now = new Date().toISOString()
  return {
    id: '',
    name: '',
    description: '',
    persona_prompt: '',
    style_rules: [],
    behavior_rules: [],
    permission_boundary: '人格不得扩大系统级权限；不得绕过管理员审核、工具权限、工作区限制或安全策略。',
    version: 1,
    status: 'active',
    created_at: now,
    updated_at: now,
  }
}

export function PersonaPanel() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedId, setSelectedId] = useState(BASE_ID)
  const [draft, setDraft] = useState<Persona>(emptyDraft())
  const [styleText, setStyleText] = useState('')
  const [behaviorText, setBehaviorText] = useState('')
  const [bindings, setBindings] = useState<PersonaBindings>({ agents: {}, sessions: {} })
  const [agents, setAgents] = useState<string[]>([])
  const [proposals, setProposals] = useState<PersonaProposal[]>([])
  const [versions, setVersions] = useState<PersonaVersion[]>([])
  const [feedback, setFeedback] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [reviewer, setReviewer] = useState('local-admin')
  const [notice, setNotice] = useState('')
  const [showArchived, setShowArchived] = useState(false)

  const selected = useMemo(
    () => personas.find((item) => item.id === selectedId) || personas[0],
    [personas, selectedId]
  )

  const refresh = useCallback(async () => {
    const [personaRes, bindingRes, proposalRes, agentRes] = await Promise.all([
      listPersonas(showArchived),
      getPersonaBindings(),
      listPersonaProposals(),
      getAgents(),
    ])
    if (personaRes.status === 'ok' && personaRes.data) setPersonas(personaRes.data)
    if (bindingRes.status === 'ok' && bindingRes.data) setBindings(bindingRes.data)
    if (proposalRes.status === 'ok' && proposalRes.data) setProposals(proposalRes.data)
    if (agentRes.status === 'ok' && agentRes.data) setAgents(agentRes.data.map((agent) => agent.name))
  }, [showArchived])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    if (!selected) return
    setDraft(selected)
    setStyleText(listToText(selected.style_rules))
    setBehaviorText(listToText(selected.behavior_rules))
    listPersonaVersions(selected.id).then((res) => {
      if (res.status === 'ok' && res.data) setVersions(res.data.slice().reverse())
    })
  }, [selected])

  const saveDraft = async () => {
    const payload = {
      ...draft,
      style_rules: linesToList(styleText),
      behavior_rules: linesToList(behaviorText),
    }
    const res = draft.id
      ? await updatePersona(draft.id, payload)
      : await createPersona({ ...payload, name: payload.name || '新人格' })
    setNotice(res.status === 'ok' ? '人格已保存' : res.message || '保存失败')
    await refresh()
    if (res.status === 'ok' && res.data) setSelectedId((res.data as Persona).id)
  }

  const generateProposal = async () => {
    if (!selected) return
    const res = await createPersonaProposal(selected.id, {
      source: 'admin_instruction',
      feedback: feedback || '请根据最近反馈优化人格。',
      session_id: sessionId || undefined,
    })
    setNotice(res.status === 'ok' ? '建议已进入待审核队列，未自动覆盖人格正文' : res.message || '生成失败')
    setFeedback('')
    await refresh()
  }

  const bindAgent = async (agent: string, personaId: string) => {
    const res = await bindAgentPersona(agent, personaId)
    setNotice(res.status === 'ok' ? `Agent ${agent} 已绑定人格` : res.message || '绑定失败')
    await refresh()
  }

  const bindSession = async () => {
    if (!sessionId || !selected) return
    const res = await bindSessionPersona(sessionId, selected.id)
    setNotice(res.status === 'ok' ? '会话已绑定当前人格' : res.message || '绑定失败')
    await refresh()
  }

  return (
    <div className="persona-panel">
      <header className="persona-hero">
        <div>
          <span className="persona-kicker">Persona Governance</span>
          <h2>人格系统</h2>
          <p>创建、绑定、审核和回滚人格。迭代建议必须人工批准，禁止自动覆盖正文。</p>
        </div>
        <button className="persona-primary" onClick={() => { setSelectedId(''); setDraft(emptyDraft()); setStyleText(''); setBehaviorText('') }}>新建人格</button>
      </header>

      {notice && <div className="persona-notice">{notice}</div>}

      <div className="persona-grid">
        <aside className="persona-list-card">
          <label className="persona-check"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> 显示归档</label>
          <div className="persona-list">
            {personas.map((persona) => (
              <button key={persona.id} className={`persona-list-item ${persona.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(persona.id)}>
                <strong>{persona.name}</strong>
                <span>v{persona.version} · {persona.status}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="persona-editor-card">
          <div className="persona-form-row">
            <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="人格名称" />
            <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as Persona['status'] })}>
              <option value="active">active</option><option value="draft">draft</option><option value="archived">archived</option>
            </select>
          </div>
          <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="描述" rows={2} />
          <textarea value={draft.persona_prompt} onChange={(e) => setDraft({ ...draft, persona_prompt: e.target.value })} placeholder="persona/system prompt 片段" rows={5} />
          <div className="persona-two-cols">
            <label>风格规则<textarea value={styleText} onChange={(e) => setStyleText(e.target.value)} rows={6} /></label>
            <label>行为规则<textarea value={behaviorText} onChange={(e) => setBehaviorText(e.target.value)} rows={6} /></label>
          </div>
          <label>权限/边界说明<textarea value={draft.permission_boundary} onChange={(e) => setDraft({ ...draft, permission_boundary: e.target.value })} rows={3} /></label>
          <div className="persona-actions">
            <button className="persona-primary" onClick={saveDraft}>保存</button>
            {draft.id && draft.id !== BASE_ID && draft.status !== 'archived' && <button onClick={async () => { await archivePersona(draft.id); await refresh() }}>归档</button>}
            {draft.id && draft.status === 'archived' && <button onClick={async () => { await restorePersona(draft.id); await refresh() }}>恢复</button>}
          </div>
        </section>
      </div>

      <div className="persona-grid persona-grid--bottom">
        <section className="persona-card">
          <h3>绑定生效</h3>
          <p className="persona-muted">请求指定人格 &gt; 会话绑定 &gt; Agent 绑定 &gt; 基础人格。</p>
          <div className="persona-bindings">
            {agents.map((agent) => (
              <label key={agent}>{agent}<select value={bindings.agents[agent] || BASE_ID} onChange={(e) => bindAgent(agent, e.target.value)}>{personas.filter((p) => p.status === 'active').map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            ))}
          </div>
          <div className="persona-form-row">
            <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} placeholder="session_id" />
            <button onClick={bindSession} disabled={!sessionId || !selected}>绑定当前人格到会话</button>
          </div>
        </section>

        <section className="persona-card">
          <h3>生成迭代建议</h3>
          <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="输入对话反馈、管理员指令或反思摘要。建议只进入待审核，不会自动覆盖。" rows={5} />
          <button className="persona-primary" onClick={generateProposal} disabled={!selected}>生成待审核建议</button>
        </section>
      </div>

      <section className="persona-card">
        <h3>迭代建议审核</h3>
        <div className="persona-reviewer"><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="reviewer" /></div>
        <div className="persona-proposals">
          {proposals.map((proposal) => (
            <article key={proposal.id} className={`persona-proposal persona-proposal--${proposal.status}`}>
              <div><strong>{proposal.source}</strong><span>{proposal.status} · {proposal.persona_id} @ v{proposal.base_version}</span></div>
              <p>{proposal.summary}</p>
              <details><summary>查看 diff / 变更说明</summary><pre>{proposal.diff}</pre><pre>{proposal.proposal_text}</pre></details>
              {proposal.status === 'pending' && <div className="persona-actions"><button className="persona-primary" onClick={async () => { await approvePersonaProposal(proposal.id, reviewer); await refresh() }}>批准生成新版本</button><button onClick={async () => { await rejectPersonaProposal(proposal.id, reviewer); await refresh() }}>拒绝</button></div>}
            </article>
          ))}
        </div>
      </section>

      <section className="persona-card">
        <h3>版本历史 / 回滚</h3>
        <div className="persona-version-list">
          {versions.map((version) => (
            <div key={`${version.version}-${version.created_at}`} className="persona-version-item">
              <span>v{version.version} · {version.reason} · {new Date(version.created_at).toLocaleString()}</span>
              {selected && version.version !== selected.version && <button onClick={async () => { if (window.confirm(`确认回滚到 v${version.version}？会生成新的版本。`)) { await rollbackPersona(selected.id, version.version, reviewer); await refresh() } }}>回滚到此版本</button>}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
