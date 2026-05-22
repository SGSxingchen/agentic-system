import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { Memory, MemorySettings } from '../types'
import './MemoryPanel.css'

type MemoryCenterTab = 'overview' | 'memories' | 'recall' | 'create' | 'settings'

interface MemoryPanelProps {
  onClose?: () => void
  initialTab?: MemoryCenterTab
}

const MEMORY_TYPES = ['episodic', 'semantic', 'procedural'] as const
const LIST_TYPES = ['', ...MEMORY_TYPES] as const

const TYPE_LABELS: Record<string, string> = {
  episodic: '情景记忆',
  semantic: '语义记忆',
  procedural: '流程记忆',
}

const KIND_LABELS: Record<string, string> = {
  preference: '偏好',
  fact: '事实',
  project_context: '项目背景',
  decision: '决策',
  todo: '待办',
  experience: '经验',
  other: '其他',
}

const TYPE_COLORS: Record<string, string> = {
  episodic: '#2f6f9f',
  semantic: '#6f5aa8',
  procedural: '#9a6a22',
}

interface EditFormState {
  content: string
  type: string
  importance: number
  metadataJson: string
}

interface CreateFormState {
  content: string
  type: string
  importance: number
  kind: string
  topics: string
  source: string
  confidence: number
}

const defaultCreateForm: CreateFormState = {
  content: '',
  type: 'semantic',
  importance: 0.6,
  kind: 'other',
  topics: '',
  source: 'manual',
  confidence: 0.8,
}

const formatDate = (value?: string) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

const pct = (value?: number | null) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

const clamp01 = (value: number) => Math.max(0, Math.min(1, value))
const getMetadata = (memory?: Memory | null) => memory?.metadata || {}

const getMemoryKind = (memory?: Memory | null) => {
  const value = getMetadata(memory).memory_kind
  return typeof value === 'string' && value ? value : 'other'
}

const getTopics = (memory?: Memory | null): string[] => {
  const topics = getMetadata(memory).topics
  return Array.isArray(topics) ? topics.map(String).filter(Boolean) : []
}

const getSource = (memory?: Memory | null) => {
  const metadata = getMetadata(memory)
  const source = metadata.source || metadata.source_window?.source || metadata.session_id
  return typeof source === 'string' && source ? source : '-'
}

const getConfidence = (memory?: Memory | null) => {
  const metadata = getMetadata(memory)
  return typeof metadata.confidence === 'number' ? metadata.confidence : null
}

const getQuality = (memory?: Memory | null) => {
  const metadata = getMetadata(memory)
  return typeof metadata.summary_quality === 'number' ? metadata.summary_quality : null
}

const getPreview = (content: string, max = 150) => {
  const normalized = content.replace(/\s+/g, ' ').trim()
  if (normalized.length <= max) return normalized
  return `${normalized.slice(0, max)}...`
}

export function MemoryPanel({ onClose, initialTab = 'overview' }: MemoryPanelProps) {
  const [activeTab, setActiveTab] = useState<MemoryCenterTab>(initialTab)
  const [stats, setStats] = useState<api.MemoryStatsResponse | null>(null)
  const [settings, setSettings] = useState<MemorySettings | null>(null)
  const [settingsForm, setSettingsForm] = useState<MemorySettings | null>(null)
  const [memories, setMemories] = useState<Memory[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [listType, setListType] = useState<string>('')
  const [listLimit, setListLimit] = useState(50)
  const [minImportance, setMinImportance] = useState(0)
  const [keyword, setKeyword] = useState('')
  const [recallQuery, setRecallQuery] = useState('')
  const [recallLimit, setRecallLimit] = useState(5)
  const [recallResults, setRecallResults] = useState<Memory[]>([])
  const [createForm, setCreateForm] = useState<CreateFormState>(defaultCreateForm)
  const [editForm, setEditForm] = useState<EditFormState | null>(null)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [saving, setSaving] = useState(false)
  const [operating, setOperating] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    setActiveTab(initialTab)
  }, [initialTab])

  const showNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(null), 3200)
  }

  const loadStats = useCallback(async () => {
    const res = await api.getMemoryStats()
    if (res.status === 'ok' && res.data) setStats(res.data)
    else setError(res.message || '记忆统计加载失败')
  }, [])

  const loadSettings = useCallback(async () => {
    const res = await api.getMemorySettings()
    if (res.status === 'ok' && res.data) {
      setSettings(res.data)
      setSettingsForm(res.data)
    } else {
      setError(res.message || '记忆设置加载失败')
    }
  }, [])

  const loadMemories = useCallback(async () => {
    const res = await api.listMemories(listType || undefined, listLimit)
    if (res.status === 'ok' && res.data) {
      setMemories(res.data)
      setSelectedId((current) => {
        if (current && res.data?.some((item) => item.id === current)) return current
        return res.data?.[0]?.id || null
      })
    } else {
      setError(res.message || '记忆列表加载失败')
    }
  }, [listLimit, listType])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    await Promise.all([loadStats(), loadSettings(), loadMemories()])
    setLoading(false)
  }, [loadStats, loadMemories, loadSettings])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  const filteredMemories = useMemo(() => {
    return memories.filter((memory) => {
      if (memory.importance < minImportance) return false
      const text = `${memory.content} ${JSON.stringify(memory.metadata || {})}`.toLowerCase()
      return !keyword.trim() || text.includes(keyword.trim().toLowerCase())
    })
  }, [keyword, memories, minImportance])

  const detailMemories = activeTab === 'recall' ? recallResults : filteredMemories
  const selectedMemory =
    detailMemories.find((item) => item.id === selectedId) ||
    detailMemories[0] ||
    null

  const total = stats?.total_memories ?? stats?.total ?? 0
  const byType = stats?.by_type || { episodic: 0, semantic: 0, procedural: 0 }
  const backendStatus = settings?.status

  const openEdit = (memory: Memory) => {
    setEditing(true)
    setEditForm({
      content: memory.content,
      type: memory.type,
      importance: memory.importance,
      metadataJson: JSON.stringify(memory.metadata || {}, null, 2),
    })
  }

  const handleSaveEdit = async () => {
    if (!selectedMemory || !editForm) return
    if (!editForm.content.trim()) {
      setError('记忆内容不能为空')
      return
    }

    let metadata: Record<string, unknown>
    try {
      const parsed = editForm.metadataJson.trim() ? JSON.parse(editForm.metadataJson) : {}
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('元数据必须是 JSON 对象')
      }
      metadata = parsed as Record<string, unknown>
    } catch (err) {
      setError(err instanceof Error ? err.message : '元数据 JSON 解析失败')
      return
    }

    setSaving(true)
    setError(null)
    const res = await api.updateMemory(selectedMemory.id, {
      content: editForm.content.trim(),
      type: editForm.type,
      importance: clamp01(editForm.importance),
      metadata,
    })
    if (res.status === 'ok' && res.data) {
      setMemories((items) => items.map((item) => (item.id === res.data!.id ? res.data! : item)))
      setRecallResults((items) => items.map((item) => (item.id === res.data!.id ? res.data! : item)))
      setEditing(false)
      setEditForm(null)
      showNotice('记忆已更新')
      await loadStats()
    } else {
      setError(res.message || '保存记忆失败')
    }
    setSaving(false)
  }

  const handleDelete = async (memory: Memory) => {
    const confirmed = window.confirm(`确认删除这条记忆？\n\n${getPreview(memory.content, 80)}`)
    if (!confirmed) return
    setOperating(memory.id)
    setError(null)
    const res = await api.deleteMemory(memory.id)
    if (res.status === 'ok') {
      showNotice('记忆已删除')
      setMemories((items) => items.filter((item) => item.id !== memory.id))
      setRecallResults((items) => items.filter((item) => item.id !== memory.id))
      setSelectedId(null)
      await loadStats()
    } else {
      setError(res.message || '删除失败')
    }
    setOperating(null)
  }

  const handleConsolidate = async () => {
    if (!window.confirm('系统将按后端规则合并重复记忆并强化主记忆。是否继续？')) return
    setOperating('consolidate')
    setError(null)
    const res = await api.consolidateMemories()
    if (res.status === 'ok') {
      showNotice(`巩固完成：${JSON.stringify(res.data || {})}`)
      await refreshAll()
    } else {
      setError(res.message || '巩固失败')
    }
    setOperating(null)
  }

  const handleForget = async () => {
    if (!window.confirm('将推进一个遗忘周期。系统只会清理长期未访问、低重要性且非待办/非高质量的记忆。是否继续？')) return
    setOperating('forget')
    setError(null)
    const res = await api.forgetMemories()
    if (res.status === 'ok' && res.data) {
      showNotice(`遗忘周期已完成：删除 ${res.data.forgotten} 条；周期 ${res.data.cycle_days} 天；截止 ${formatDate(res.data.cutoff)}`)
      await refreshAll()
    } else {
      setError(res.message || '遗忘周期执行失败')
    }
    setOperating(null)
  }

  const handleRecall = async () => {
    if (!recallQuery.trim()) {
      setError('请输入召回测试查询')
      return
    }
    setSearching(true)
    setError(null)
    const res = await api.searchMemories(recallQuery.trim(), recallLimit)
    if (res.status === 'ok' && res.data) {
      setRecallResults(res.data)
      setSelectedId(res.data[0]?.id || null)
      if (res.data.length === 0) showNotice('没有召回结果')
    } else {
      setError(res.message || '召回测试失败')
    }
    setSearching(false)
  }

  const handleCreate = async () => {
    if (!createForm.content.trim()) {
      setError('记忆内容不能为空')
      return
    }
    setSaving(true)
    setError(null)
    const topics = createForm.topics.split(',').map((item) => item.trim()).filter(Boolean)
    const metadata: Record<string, unknown> = {
      memory_kind: createForm.kind,
      source: createForm.source.trim() || 'manual',
      confidence: clamp01(createForm.confidence),
      manually_created: true,
    }
    if (topics.length > 0) metadata.topics = topics

    const res = await api.createMemory({
      content: createForm.content.trim(),
      type: createForm.type,
      importance: clamp01(createForm.importance),
      metadata,
    })
    if (res.status === 'ok' && res.data) {
      showNotice('记忆已创建')
      setCreateForm(defaultCreateForm)
      setActiveTab('memories')
      await refreshAll()
      setSelectedId(res.data.id)
    } else {
      setError(res.message || '创建失败')
    }
    setSaving(false)
  }

  const patchSettings = (patch: Partial<MemorySettings>) => {
    setSettingsForm((current) => (current ? { ...current, ...patch } : current))
  }

  const saveSettings = async () => {
    if (!settingsForm) return
    if (settingsForm.reflection_min_turns < 1) {
      setError('反思触发轮数必须大于等于 1')
      return
    }
    if (settingsForm.reflection_max_messages < 2) {
      setError('反思窗口消息数必须大于等于 2')
      return
    }
    if (settingsForm.recall_max_results < 1 || settingsForm.recall_max_results > 50) {
      setError('召回数量必须在 1-50 之间')
      return
    }
    setSaving(true)
    setError(null)
    const persistableSettings: Partial<MemorySettings> = { ...settingsForm }
    delete persistableSettings.status
    const res = await api.updateMemorySettings(persistableSettings)
    if (res.status === 'ok' && res.data) {
      setSettings(res.data)
      setSettingsForm(res.data)
      showNotice(res.message || '记忆设置已保存')
    } else {
      setError(res.message || '保存设置失败')
    }
    setSaving(false)
  }

  const renderMetric = (label: string, value: string | number, hint?: string) => (
    <div className="mc-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )

  const renderMemoryCard = (memory: Memory) => {
    const selected = selectedMemory?.id === memory.id
    const topics = getTopics(memory)
    const retrievalScore = memory.retrieval?.score
    return (
      <article
        key={memory.id}
        className={`mc-memory-card ${selected ? 'selected' : ''}`}
        onClick={() => {
          setSelectedId(memory.id)
          setEditing(false)
        }}
      >
        <div className="mc-memory-card-top">
          <span className="mc-type-pill" style={{ ['--type-color' as string]: TYPE_COLORS[memory.type] || '#64748b' }}>
            {TYPE_LABELS[memory.type] || memory.type}
          </span>
          <span className="mc-kind-pill">{KIND_LABELS[getMemoryKind(memory)] || getMemoryKind(memory)}</span>
          {retrievalScore != null && <span className="mc-score-pill">召回 {pct(retrievalScore)}</span>}
        </div>
        <p>{getPreview(memory.content)}</p>
        {topics.length > 0 && (
          <div className="mc-tags">
            {topics.slice(0, 4).map((topic) => <span key={topic}>#{topic}</span>)}
          </div>
        )}
        <div className="mc-memory-card-meta">
          <span>重要性 {pct(memory.importance)}</span>
          <span>访问 {memory.access_count ?? 0}</span>
          <span>{formatDate(memory.created_at)}</span>
        </div>
      </article>
    )
  }

  const renderDetail = () => {
    if (!selectedMemory) {
      return (
        <aside className="mc-detail mc-empty-detail">
          <h3>请选择一条记忆</h3>
          <p>左侧列表或召回结果会在此展示完整内容、来源、评分与元数据。</p>
        </aside>
      )
    }

    const metadata = getMetadata(selectedMemory)
    const topics = getTopics(selectedMemory)
    const retrieval = selectedMemory.retrieval

    return (
      <aside className="mc-detail">
        <div className="mc-detail-header">
          <div>
            <span className="mc-eyebrow">记忆详情</span>
            <h3>{TYPE_LABELS[selectedMemory.type] || selectedMemory.type}</h3>
          </div>
          <div className="mc-detail-actions">
            {!editing && <button className="mc-ghost-btn" onClick={() => openEdit(selectedMemory)}>编辑</button>}
            <button className="mc-danger-btn" onClick={() => handleDelete(selectedMemory)} disabled={operating === selectedMemory.id}>
              删除
            </button>
          </div>
        </div>

        {editing && editForm ? (
          <div className="mc-edit-form">
            <label>
              内容
              <textarea rows={7} value={editForm.content} onChange={(event) => setEditForm({ ...editForm, content: event.target.value })} />
            </label>
            <div className="mc-form-grid two">
              <label>
                类型
                <select value={editForm.type} onChange={(event) => setEditForm({ ...editForm, type: event.target.value })}>
                  {MEMORY_TYPES.map((type) => <option key={type} value={type}>{TYPE_LABELS[type]}</option>)}
                </select>
              </label>
              <label>
                重要性 {pct(editForm.importance)}
                <input type="range" min="0" max="1" step="0.05" value={editForm.importance} onChange={(event) => setEditForm({ ...editForm, importance: Number(event.target.value) })} />
              </label>
            </div>
            <label>
              元数据 JSON
              <textarea rows={9} className="mc-code-textarea" value={editForm.metadataJson} onChange={(event) => setEditForm({ ...editForm, metadataJson: event.target.value })} />
            </label>
            <div className="mc-form-actions">
              <button className="mc-ghost-btn" onClick={() => { setEditing(false); setEditForm(null) }}>取消</button>
              <button className="mc-primary-btn" onClick={handleSaveEdit} disabled={saving}>{saving ? '保存中...' : '保存编辑'}</button>
            </div>
          </div>
        ) : (
          <>
            <div className="mc-detail-content">{selectedMemory.content}</div>
            <div className="mc-detail-grid">
              <div><span>重要性</span><strong>{pct(selectedMemory.importance)}</strong></div>
              <div><span>置信度</span><strong>{pct(getConfidence(selectedMemory))}</strong></div>
              <div><span>摘要质量</span><strong>{pct(getQuality(selectedMemory))}</strong></div>
              <div><span>访问次数</span><strong>{selectedMemory.access_count ?? 0}</strong></div>
              <div><span>来源</span><strong>{getSource(selectedMemory)}</strong></div>
              <div><span>最后访问</span><strong>{formatDate(selectedMemory.last_accessed)}</strong></div>
            </div>
            {topics.length > 0 && (
              <div className="mc-detail-section">
                <span className="mc-section-label">标签</span>
                <div className="mc-tags large">{topics.map((topic) => <span key={topic}>#{topic}</span>)}</div>
              </div>
            )}
            {retrieval && (
              <div className="mc-detail-section">
                <span className="mc-section-label">召回评分解释</span>
                <div className="mc-score-stack">
                  {Object.entries(retrieval.breakdown || {}).map(([key, value]) => (
                    <div key={key} className="mc-score-row">
                      <span>{key}</span>
                      <div><i style={{ width: pct(value) }} /></div>
                      <strong>{pct(value)}</strong>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="mc-detail-section">
              <span className="mc-section-label">元数据</span>
              <pre className="mc-json-block">{JSON.stringify(metadata, null, 2)}</pre>
            </div>
            <div className="mc-id-line">ID: {selectedMemory.id}</div>
          </>
        )}
      </aside>
    )
  }

  const renderOverview = () => (
    <div className="mc-overview">
      <section className="mc-hero-card">
        <div>
          <h2>长期记忆运行概览</h2>
          <p>该页面集中管理记忆检索、人工维护、自动反思参数与遗忘周期，供演示和评审时快速确认系统状态。</p>
        </div>
        <button className="mc-ghost-btn" onClick={refreshAll} disabled={loading}>刷新数据</button>
      </section>

      <div className="mc-metrics-grid">
        {renderMetric('记忆总数', total, '当前存储中的有效记忆')}
        {renderMetric('情景记忆', byType.episodic || 0)}
        {renderMetric('语义记忆', byType.semantic || 0)}
        {renderMetric('流程记忆', byType.procedural || 0)}
      </div>

      <section className="mc-status-card">
        <div className="mc-settings-head">
          <div>
            <span className="mc-eyebrow">运行状态</span>
            <h3>存储与反思配置</h3>
          </div>
          <button className="mc-ghost-btn" onClick={() => setActiveTab('settings')}>查看设置</button>
        </div>
        <div className="mc-status-grid">
          <div><span>后端</span><strong>{settings?.backend || '-'}</strong></div>
          <div><span>运行存储</span><strong>{backendStatus?.runtime_store || '-'}</strong></div>
          <div><span>初始化</span><strong>{backendStatus?.initialized ? '已初始化' : '未初始化'}</strong></div>
          <div><span>自动反思</span><strong>{settings?.auto_reflection_enabled ? '已启用' : '已关闭'}</strong></div>
          <div><span>默认召回</span><strong>{settings?.recall_max_results ?? '-'}</strong></div>
          <div><span>遗忘周期</span><strong>{settings?.forget_after_days ?? '-'} 天</strong></div>
        </div>
      </section>
    </div>
  )

  const renderMemories = () => (
    <div className="mc-browser-layout">
      <section className="mc-list-pane">
        <div className="mc-toolbar">
          <select value={listType} onChange={(event) => setListType(event.target.value)}>
            {LIST_TYPES.map((type) => <option key={type || 'all'} value={type}>{type ? TYPE_LABELS[type] : '全部类型'}</option>)}
          </select>
          <input type="number" min="1" max="200" value={listLimit} onChange={(event) => setListLimit(Number(event.target.value))} />
          <button className="mc-ghost-btn" onClick={loadMemories}>刷新</button>
        </div>
        <div className="mc-toolbar secondary">
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="按正文或元数据过滤" />
          <label className="mc-range-filter">
            最低重要性 {pct(minImportance)}
            <input type="range" min="0" max="1" step="0.05" value={minImportance} onChange={(event) => setMinImportance(Number(event.target.value))} />
          </label>
        </div>
        <div className="mc-memory-list">
          {filteredMemories.length === 0 ? (
            <div className="mc-state empty">
              <strong>暂无匹配记忆</strong>
              <p>请调整筛选条件，或在“创建记忆”中手动补充评审演示所需的长期信息。</p>
            </div>
          ) : filteredMemories.map(renderMemoryCard)}
        </div>
      </section>
      {renderDetail()}
    </div>
  )

  const renderRecall = () => (
    <div className="mc-browser-layout">
      <section className="mc-list-pane">
        <div className="mc-recall-box">
          <h3>召回测试</h3>
          <p>输入一段用户上下文，检查长期记忆检索结果及评分解释。</p>
          <textarea rows={5} value={recallQuery} onChange={(event) => setRecallQuery(event.target.value)} placeholder="例如：用户正在准备毕业设计答辩，需要正式、准确的中文说明。" />
          <div className="mc-toolbar compact">
            <input type="number" min="1" max="20" value={recallLimit} onChange={(event) => setRecallLimit(Number(event.target.value))} />
            <button className="mc-primary-btn" onClick={handleRecall} disabled={searching}>{searching ? '召回中...' : '执行召回测试'}</button>
          </div>
        </div>
        <div className="mc-memory-list">
          {recallResults.length === 0 ? (
            <div className="mc-state empty"><strong>暂无召回结果</strong><p>执行测试后，候选记忆会显示在此处。</p></div>
          ) : recallResults.map(renderMemoryCard)}
        </div>
      </section>
      {renderDetail()}
    </div>
  )

  const renderCreate = () => (
    <div className="mc-form-page">
      <section className="mc-form-card">
        <h3>创建人工记忆</h3>
        <p>用于补充明确、稳定、可复用的长期信息。临时日志或敏感信息不应写入长期记忆。</p>
        <label>
          记忆内容
          <textarea rows={7} value={createForm.content} onChange={(event) => setCreateForm({ ...createForm, content: event.target.value })} placeholder="输入需要长期保留的事实、偏好、决策或经验。" />
        </label>
        <div className="mc-form-grid two">
          <label>
            类型
            <select value={createForm.type} onChange={(event) => setCreateForm({ ...createForm, type: event.target.value })}>
              {MEMORY_TYPES.map((type) => <option key={type} value={type}>{TYPE_LABELS[type]}</option>)}
            </select>
          </label>
          <label>
            记忆类别
            <select value={createForm.kind} onChange={(event) => setCreateForm({ ...createForm, kind: event.target.value })}>
              {Object.entries(KIND_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <label>
            重要性 {pct(createForm.importance)}
            <input type="range" min="0" max="1" step="0.05" value={createForm.importance} onChange={(event) => setCreateForm({ ...createForm, importance: Number(event.target.value) })} />
          </label>
          <label>
            置信度 {pct(createForm.confidence)}
            <input type="range" min="0" max="1" step="0.05" value={createForm.confidence} onChange={(event) => setCreateForm({ ...createForm, confidence: Number(event.target.value) })} />
          </label>
          <label>
            来源
            <input value={createForm.source} onChange={(event) => setCreateForm({ ...createForm, source: event.target.value })} />
          </label>
          <label>
            标签
            <input value={createForm.topics} onChange={(event) => setCreateForm({ ...createForm, topics: event.target.value })} placeholder="多个标签用英文逗号分隔" />
          </label>
        </div>
        <div className="mc-form-actions">
          <button className="mc-primary-btn" onClick={handleCreate} disabled={saving}>{saving ? '创建中...' : '创建记忆'}</button>
        </div>
      </section>
    </div>
  )

  const renderSettings = () => {
    if (!settingsForm) {
      return <div className="mc-state empty"><strong>设置未加载</strong><p>请刷新页面后重试。</p></div>
    }
    return (
      <div className="mc-settings-page">
        <section className="mc-form-card wide">
          <div className="mc-settings-head">
            <div>
              <h3>记忆设置</h3>
              <p>管理存储、自动反思、召回预算、巩固与遗忘策略。设置与记忆管理同属长期记忆中心。</p>
            </div>
            <button className="mc-danger-btn" onClick={handleForget} disabled={operating === 'forget'}>
              {operating === 'forget' ? '推进中...' : '推进遗忘周期'}
            </button>
          </div>

          <div className="mc-settings-section">
            <h4>存储后端</h4>
            <div className="mc-form-grid two">
              <label>
                后端
                <select value={settingsForm.backend} onChange={(event) => patchSettings({ backend: event.target.value })}>
                  <option value="chroma">ChromaDB</option>
                  <option value="memory">内存存储</option>
                </select>
              </label>
              <label>
                Collection
                <input value={settingsForm.collection_name} onChange={(event) => patchSettings({ collection_name: event.target.value })} />
              </label>
              <label className="span-2">
                持久化目录
                <input value={settingsForm.persist_dir} onChange={(event) => patchSettings({ persist_dir: event.target.value })} />
              </label>
              <label className="mc-switch-row span-2">
                <input type="checkbox" checked={settingsForm.fallback_to_memory_on_error} onChange={(event) => patchSettings({ fallback_to_memory_on_error: event.target.checked })} />
                <span>后端不可用时降级为内存存储</span>
              </label>
            </div>
          </div>

          <div className="mc-settings-section">
            <h4>自动反思与召回</h4>
            <div className="mc-form-grid two">
              <label className="mc-switch-row span-2">
                <input type="checkbox" checked={settingsForm.auto_reflection_enabled} onChange={(event) => patchSettings({ auto_reflection_enabled: event.target.checked })} />
                <span>启用对话反思生成长期记忆</span>
              </label>
              <label>
                反思触发轮数
                <input type="number" min={1} value={settingsForm.reflection_min_turns} onChange={(event) => patchSettings({ reflection_min_turns: Number(event.target.value) })} />
              </label>
              <label>
                反思窗口消息数
                <input type="number" min={2} value={settingsForm.reflection_max_messages} onChange={(event) => patchSettings({ reflection_max_messages: Number(event.target.value) })} />
              </label>
              <label>
                召回数量
                <input type="number" min={1} max={50} value={settingsForm.recall_max_results} onChange={(event) => patchSettings({ recall_max_results: Number(event.target.value) })} />
              </label>
              <label>
                召回字符预算
                <input type="number" min={200} value={settingsForm.recall_max_chars} onChange={(event) => patchSettings({ recall_max_chars: Number(event.target.value) })} />
              </label>
              <label>
                召回阈值 {pct(settingsForm.recall_score_threshold)}
                <input type="range" min="0" max="1" step="0.05" value={settingsForm.recall_score_threshold} onChange={(event) => patchSettings({ recall_score_threshold: Number(event.target.value) })} />
              </label>
            </div>
          </div>

          <div className="mc-settings-section">
            <h4>巩固与遗忘</h4>
            <div className="mc-form-grid two">
              <label>
                巩固相似度阈值 {pct(settingsForm.consolidation_threshold)}
                <input type="range" min="0" max="1" step="0.05" value={settingsForm.consolidation_threshold} onChange={(event) => patchSettings({ consolidation_threshold: Number(event.target.value) })} />
              </label>
              <label>
                遗忘重要性阈值 {pct(settingsForm.forget_min_importance)}
                <input type="range" min="0" max="1" step="0.05" value={settingsForm.forget_min_importance} onChange={(event) => patchSettings({ forget_min_importance: Number(event.target.value) })} />
              </label>
              <label>
                遗忘周期天数
                <input type="number" min={1} value={settingsForm.forget_after_days} onChange={(event) => patchSettings({ forget_after_days: Number(event.target.value) })} />
              </label>
              <div className="mc-runtime-note">
                <strong>保护规则</strong>
                <span>待办记忆、高质量摘要和高重要性记忆不会被手动周期清理。</span>
              </div>
            </div>
          </div>

          <div className="mc-form-actions">
            <button className="mc-ghost-btn" onClick={handleConsolidate} disabled={operating === 'consolidate'}>{operating === 'consolidate' ? '巩固中...' : '执行记忆巩固'}</button>
            <button className="mc-primary-btn" onClick={saveSettings} disabled={saving}>{saving ? '保存中...' : '保存设置'}</button>
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className={onClose ? 'memory-overlay' : 'memory-page-shell'}>
      <div className="memory-center">
        <header className="mc-header">
          <div>
            <span className="mc-eyebrow">长期记忆</span>
            <h1>长期记忆中心</h1>
            <p>集中管理记忆数据、召回测试、运行设置与遗忘周期。</p>
          </div>
          <div className="mc-header-actions">
            <button className="mc-ghost-btn" onClick={handleConsolidate} disabled={operating === 'consolidate'}>{operating === 'consolidate' ? '巩固中...' : '记忆巩固'}</button>
            <button className="mc-danger-btn" onClick={handleForget} disabled={operating === 'forget'}>{operating === 'forget' ? '推进中...' : '推进遗忘周期'}</button>
            {onClose && <button className="mc-close-btn" onClick={onClose} aria-label="关闭">×</button>}
          </div>
        </header>

        <nav className="mc-tabs" aria-label="记忆中心导航">
          {[
            ['overview', '总览'],
            ['memories', '记忆管理'],
            ['recall', '召回测试'],
            ['create', '创建记忆'],
            ['settings', '运行设置'],
          ].map(([key, label]) => (
            <button key={key} className={activeTab === key ? 'active' : ''} onClick={() => setActiveTab(key as MemoryCenterTab)}>{label}</button>
          ))}
        </nav>

        {error && <div className="mc-alert error"><strong>错误</strong><span>{error}</span><button onClick={() => setError(null)}>×</button></div>}
        {notice && <div className="mc-alert success"><strong>完成</strong><span>{notice}</span></div>}

        <main className="mc-body">
          {activeTab === 'overview' && renderOverview()}
          {activeTab === 'memories' && renderMemories()}
          {activeTab === 'recall' && renderRecall()}
          {activeTab === 'create' && renderCreate()}
          {activeTab === 'settings' && renderSettings()}
        </main>
      </div>
    </div>
  )
}
