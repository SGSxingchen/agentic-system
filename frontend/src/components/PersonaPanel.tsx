import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAppStore } from '../store/appStore'
import type { Persona, PersonaBindings, PersonaProposal, PersonaVersion } from '../types'
import {
  approvePersonaProposal,
  archivePersona,
  createPersona,
  createPersonaProposal,
  getAgentPersonaBindings,
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
    permission_boundary: '人格配置不得扩大系统级权限，不得绕过管理员审核、工具权限、工作区限制或安全策略。',
    version: 1,
    status: 'active',
    created_at: now,
    updated_at: now,
  }
}

function renderPreview(persona: Persona): string {
  const style = (persona.style_rules || []).map((item) => `- ${item}`).join('\n') || '- 无'
  const behavior = (persona.behavior_rules || []).map((item) => `- ${item}`).join('\n') || '- 无'
  return `[当前人格 - 受控配置]
人格只能定义语气、协作习惯和非系统级行为偏好；不能授予新权限，不能覆盖系统规则、工具权限、管理员审核或用户当前明确要求。

人格：${persona.name || '未命名'}（id=${persona.id || '<new>'}，version=${persona.version || 1}）
描述：${persona.description || ''}

人格提示词：
${persona.persona_prompt || ''}

风格规则：
${style}

行为规则：
${behavior}

权限边界：
${persona.permission_boundary || ''}`
}

function statusText(status: Persona['status']) {
  return status === 'active' ? '启用' : status === 'draft' ? '草稿' : '已归档'
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
  const [bindings, setBindings] = useState<PersonaBindings | null>(null)
  const [feedback, setFeedback] = useState('')
  const [proposalSessionId, setProposalSessionId] = useState('')
  const [reviewer, setReviewer] = useState('local-admin')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [showArchived, setShowArchived] = useState(false)

  const selected = useMemo(
    () => personas.find((item) => item.id === selectedId) || personas[0],
    [personas, selectedId]
  )

  const refresh = useCallback(async (force = false) => {
    setError('')
    const cache = state.personaCache
    const now = Date.now()
    const personasFresh =
      !force &&
      cache.personasFetchedAt > 0 &&
      now - cache.personasFetchedAt < PERSONA_CACHE_TTL_MS &&
      cache.includeArchived === showArchived &&
      cache.personas.length > 0

    const [personaRes, proposalRes, bindingRes] = await Promise.all([
      personasFresh
        ? Promise.resolve({ status: 'ok' as const, data: cache.personas, message: '' })
        : listPersonas(showArchived),
      listPersonaProposals(),
      getAgentPersonaBindings(),
    ])

    if (personaRes.status === 'ok' && personaRes.data) {
      setPersonas(personaRes.data)
      dispatch({ type: 'SET_PERSONAS_CACHE', payload: { personas: personaRes.data, includeArchived: showArchived } })
      if (!personaRes.data.some((item) => item.id === selectedId)) {
        setSelectedId(personaRes.data[0]?.id || '')
      }
    } else {
      setError(personaRes.message || '人格列表加载失败')
    }
    if (proposalRes.status === 'ok' && proposalRes.data) setProposals(proposalRes.data)
    if (bindingRes.status === 'ok' && bindingRes.data) setBindings(bindingRes.data)
  }, [dispatch, selectedId, showArchived, state.personaCache])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    if (!selected) {
      setDraft(emptyDraft())
      return
    }
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
      : await createPersona({ ...payload, name: payload.name || '新建人格' })

    if (res.status === 'ok') {
      setNotice('人格定义已保存')
      dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
      await refresh(true)
      if (res.data) setSelectedId((res.data as Persona).id)
    } else {
      setError(res.message || '保存人格失败')
    }
  }

  const generateProposal = async () => {
    if (!selected) return
    const res = await createPersonaProposal(selected.id, {
      source: 'admin_instruction',
      feedback: feedback || '请根据最近反馈优化人格配置。',
      session_id: proposalSessionId || undefined,
    })
    if (res.status === 'ok') {
      setNotice('建议已进入待审核队列，不会自动覆盖人格正文')
      setFeedback('')
      await refresh(true)
    } else {
      setError(res.message || '生成建议失败')
    }
  }

  const previewPersona: Persona = {
    ...draft,
    style_rules: linesToList(styleText),
    behavior_rules: linesToList(behaviorText),
  }

  return (
    <div className="persona-panel">
      <header className="persona-page-header">
        <div>
        <span className="persona-kicker">人格治理</span>
          <h2>人格管理</h2>
          <p>管理人格定义、注入预览、版本历史与迭代建议。人格只影响表达方式和协作习惯，不改变系统权限。</p>
        </div>
        <button className="persona-primary" onClick={() => { setSelectedId(''); setDraft(emptyDraft()); setStyleText(''); setBehaviorText('') }}>新建人格</button>
      </header>

      {notice && <div className="persona-notice">{notice}</div>}
      {error && <div className="persona-error">{error}</div>}

      <div className="persona-admin-layout">
        <aside className="persona-list-pane">
          <div className="persona-pane-head">
            <h3>人格列表</h3>
            <label className="persona-check"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> 显示归档</label>
          </div>
          <div className="persona-list">
            {personas.length === 0 ? (
              <div className="persona-empty">暂无人格定义</div>
            ) : personas.map((persona) => (
              <button key={persona.id} className={`persona-list-item ${persona.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(persona.id)}>
                <strong>{persona.name}</strong>
                <span>v{persona.version} · {statusText(persona.status)}</span>
              </button>
            ))}
          </div>

          <section className="persona-binding-summary">
            <h3>绑定概览</h3>
            <p>生效优先级：请求指定人格 &gt; 会话绑定 &gt; 智能体绑定 &gt; 基础人格。</p>
            <div className="persona-binding-list">
            <span>智能体绑定：{Object.keys(bindings?.agents || {}).length}</span>
              <span>会话绑定：{Object.keys(bindings?.sessions || {}).length}</span>
              <span>基础人格：{bindings?.base_persona_id || BASE_ID}</span>
            </div>
          </section>
        </aside>

        <main className="persona-main">
          <section className="persona-editor-card">
            <div className="persona-card-title">
              <div>
                <span className="persona-kicker">Definition</span>
                <h3>人格定义</h3>
              </div>
              <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as Persona['status'] })}>
                <option value="active">启用</option>
                <option value="draft">草稿</option>
                <option value="archived">归档</option>
              </select>
            </div>
            <div className="persona-form-row">
              <label>
                名称
                <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="例如：正式评审助手" />
              </label>
              <label>
                ID
                <input value={draft.id || '保存后生成'} disabled />
              </label>
            </div>
            <label>描述<textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={2} /></label>
            <label>人格提示词<textarea value={draft.persona_prompt} onChange={(e) => setDraft({ ...draft, persona_prompt: e.target.value })} rows={5} /></label>
            <div className="persona-two-cols">
              <label>风格规则<textarea value={styleText} onChange={(e) => setStyleText(e.target.value)} rows={6} /></label>
              <label>行为规则<textarea value={behaviorText} onChange={(e) => setBehaviorText(e.target.value)} rows={6} /></label>
            </div>
            <label>权限边界<textarea value={draft.permission_boundary} onChange={(e) => setDraft({ ...draft, permission_boundary: e.target.value })} rows={3} /></label>
            <div className="persona-actions">
              <button className="persona-primary" onClick={saveDraft}>保存人格</button>
              {draft.id && draft.id !== BASE_ID && draft.status !== 'archived' && <button onClick={async () => { await archivePersona(draft.id); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) }}>归档</button>}
              {draft.id && draft.status === 'archived' && <button onClick={async () => { await restorePersona(draft.id); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) }}>恢复</button>}
            </div>
          </section>

          <section className="persona-card">
            <div className="persona-card-title">
              <div>
                <span className="persona-kicker">Preview</span>
                <h3>注入预览</h3>
              </div>
            </div>
            <pre className="persona-preview">{renderPreview(previewPersona)}</pre>
          </section>
        </main>
      </div>

      <div className="persona-admin-layout persona-admin-layout--lower">
        <section className="persona-card">
          <div className="persona-card-title">
            <div>
              <span className="persona-kicker">Proposal</span>
              <h3>生成迭代建议</h3>
            </div>
          </div>
          <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="输入对话反馈、管理员指令或反思摘要。建议只会进入待审核队列。" rows={5} />
          <input value={proposalSessionId} onChange={(e) => setProposalSessionId(e.target.value)} placeholder="可选 session_id，仅用于来源追踪" />
          <button className="persona-primary" onClick={generateProposal} disabled={!selected}>生成待审核建议</button>
        </section>

        <section className="persona-card">
          <div className="persona-card-title">
            <div>
              <span className="persona-kicker">Review</span>
              <h3>建议审核</h3>
            </div>
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="reviewer" />
          </div>
          <div className="persona-proposals">
            {proposals.length === 0 ? (
              <div className="persona-empty">暂无待处理建议</div>
            ) : proposals.map((proposal) => (
              <article key={proposal.id} className={`persona-proposal persona-proposal--${proposal.status}`}>
                <div className="persona-proposal-head"><strong>{proposal.persona_id}</strong><span>{proposal.status} · base v{proposal.base_version}</span></div>
                <p>{proposal.summary}</p>
                <details><summary>查看差异与说明</summary><pre>{proposal.diff}</pre><pre>{proposal.proposal_text}</pre></details>
                {proposal.status === 'pending' && (
                  <div className="persona-actions">
                    <button className="persona-primary" onClick={async () => { await approvePersonaProposal(proposal.id, reviewer); dispatch({ type: 'INVALIDATE_PERSONA_CACHE' }); await refresh(true) }}>批准并生成新版本</button>
                    <button onClick={async () => { await rejectPersonaProposal(proposal.id, reviewer); await refresh(true) }}>拒绝</button>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="persona-card persona-version-section">
        <div className="persona-card-title">
          <div>
            <span className="persona-kicker">Versions</span>
            <h3>版本历史</h3>
          </div>
        </div>
        <div className="persona-version-list">
          {versions.length === 0 ? (
            <div className="persona-empty">暂无版本记录</div>
          ) : versions.map((version) => (
            <div key={`${version.version}-${version.created_at}`} className="persona-version-item">
              <span>v{version.version} · {version.reason} · {new Date(version.created_at).toLocaleString('zh-CN')}</span>
              {selected && version.version !== selected.version && (
                <button onClick={async () => {
                  if (window.confirm(`确认回滚到 v${version.version}？系统会生成新的版本记录。`)) {
                    await rollbackPersona(selected.id, version.version, reviewer)
                    dispatch({ type: 'INVALIDATE_PERSONA_CACHE' })
                    await refresh(true)
                  }
                }}>回滚到此版本</button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
