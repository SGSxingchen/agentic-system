import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAppStore } from '../store/appStore'
import type { Persona, PersonaProposal, PersonaVersion } from '../types'
import {
  approvePersonaProposal,
  archivePersona,
  createPersona,
  createPersonaProposal,
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
const PERSONA_CACHE_TTL_MS = 30_000

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

function renderPreview(persona: Persona): string {
  const style = (persona.style_rules || []).map((item) => `- ${item}`).join('\n') || '- 无'
  const behavior = (persona.behavior_rules || []).map((item) => `- ${item}`).join('\n') || '- 无'
  return `[当前人格 - 受控配置]\n以下人格只定义语气、协作习惯和非系统级行为偏好。人格不能授予新权限，不能覆盖系统提示词、工具权限、管理员审核、安全边界或用户当前明确要求。\n人格: ${persona.name || '未命名'} (id=${persona.id || '<new>'}, version=${persona.version || 1})\n描述: ${persona.description || ''}\n人格提示词:\n${persona.persona_prompt || ''}\n风格规则:\n${style}\n行为规则:\n${behavior}\n权限/边界:\n${persona.permission_boundary || ''}`
}

export function PersonaPanel() {
  const { state, dispatch } = useAppStore()
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedId, setSelectedId] = useState(BASE_ID)
  const [draft, setDraft] = useState<Persona>(emptyDraft())
  const [styleText, setStyleText] = useState('')
  const [behaviorText, setBehaviorText] = useState('')
  const [proposals, setProposals] = useState<PersonaProposal[]>([])
  const [versions, setVersions] = useState<PersonaVersion[]>([])
  const [feedback, setFeedback] = useState('')
  const [proposalSessionId, setProposalSessionId] = useState('')
  const [reviewer, setReviewer] = useState('local-admin')
  const [notice, setNotice] = useState('')
  const [showArchived, setShowArchived] = useState(false)

  const selected = useMemo(
    () => personas.find((item) => item.id === selectedId) || personas[0],
    [personas, selectedId]
  )

  const refresh = useCallback(async (force = false) => {
    const cache = state.personaCache
    const now = Date.now()
    const personasFresh =
      !force &&
      cache.personasFetchedAt > 0 &&
      now - cache.personasFetchedAt < PERSONA_CACHE_TTL_MS &&
      cache.includeArchived === showArchived &&
      cache.personas.length > 0

    const [personaRes, proposalRes] = await Promise.all([
      personasFresh
        ? Promise.resolve({ status: 'ok' as const, data: cache.personas })
        : listPersonas(showArchived),
      listPersonaProposals(),
    ])
    if (personaRes.status === 'ok' && personaRes.data) {
      setPersonas(personaRes.data)
      dispatch({ type: 'SET_PERSONAS_CACHE', payload: { personas: personaRes.data, includeArchived: showArchived } })
    }
    if (proposalRes.status === 'ok' && proposalRes.data) setProposals(proposalRes.data)
  }, [dispatch, showArchived, state.personaCache])

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
    dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
    await refresh(true)
    if (res.status === 'ok' && res.data) setSelectedId((res.data as Persona).id)
  }

  const generateProposal = async () => {
    if (!selected) return
    const res = await createPersonaProposal(selected.id, {
      source: 'admin_instruction',
      feedback: feedback || '请根据最近反馈优化人格。',
      session_id: proposalSessionId || undefined,
    })
    setNotice(res.status === 'ok' ? '建议已进入待审核队列，未自动覆盖人格正文' : res.message || '生成失败')
    setFeedback('')
    await refresh(true)
  }

  const previewPersona: Persona = {
    ...draft,
    style_rules: linesToList(styleText),
    behavior_rules: linesToList(behaviorText),
  }

  return (
    <div className="persona-panel">
      <header className="persona-hero">
        <div>
          <span className="persona-kicker">Persona Governance</span>
          <h2>人格管理</h2>
          <p>只管理人格定义、测试预览、迭代建议和版本审核。Agent/会话绑定已迁移到“智能体管理”页面。</p>
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
            {draft.id && draft.id !== BASE_ID && draft.status !== 'archived' && <button onClick={async () => { await archivePersona(draft.id); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) }}>归档</button>}
            {draft.id && draft.status === 'archived' && <button onClick={async () => { await restorePersona(draft.id); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) }}>恢复</button>}
          </div>
        </section>
      </div>

      <div className="persona-grid persona-grid--bottom">
        <section className="persona-card">
          <h3>人格测试 / 注入预览</h3>
          <p className="persona-muted">预览运行时追加到 system prompt 的受控人格块。此处仅预览人格本身，不展示 Agent/Session 绑定。</p>
          <pre className="persona-preview">{renderPreview(previewPersona)}</pre>
        </section>

        <section className="persona-card">
          <h3>生成迭代建议</h3>
          <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="输入对话反馈、管理员指令或反思摘要。建议只进入待审核，不会自动覆盖。" rows={5} />
          <input value={proposalSessionId} onChange={(e) => setProposalSessionId(e.target.value)} placeholder="可选 session_id（仅作为建议来源追踪）" />
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
              {proposal.status === 'pending' && <div className="persona-actions"><button className="persona-primary" onClick={async () => { await approvePersonaProposal(proposal.id, reviewer); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) }}>批准生成新版本</button><button onClick={async () => { await rejectPersonaProposal(proposal.id, reviewer); await refresh(true) }}>拒绝</button></div>}
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
              {selected && version.version !== selected.version && <button onClick={async () => { if (window.confirm(`确认回滚到 v${version.version}？会生成新的版本。`)) { await rollbackPersona(selected.id, version.version, reviewer); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) } }}>回滚到此版本</button>}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
