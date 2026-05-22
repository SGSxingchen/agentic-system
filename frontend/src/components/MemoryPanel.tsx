import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { Memory, MemorySettings, MemoryStats } from '../types'
import './MemoryPanel.css'

const TYPE_LABEL: Record<string, string> = {
  episodic: '情景',
  semantic: '语义',
  procedural: '程序',
}

const TYPE_OPTIONS = ['', 'episodic', 'semantic', 'procedural'] as const

function formatDateTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

interface DraftMemory {
  content: string
  type: 'episodic' | 'semantic' | 'procedural'
  importance: number
}

const emptyDraft: DraftMemory = {
  content: '',
  type: 'semantic',
  importance: 0.5,
}

export function MemoryPanel() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [settings, setSettings] = useState<MemorySettings | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Memory[]>([])
  const [searching, setSearching] = useState(false)
  const [draft, setDraft] = useState<DraftMemory>(emptyDraft)
  const [editing, setEditing] = useState<Memory | null>(null)
  const [editingDraft, setEditingDraft] = useState<DraftMemory>(emptyDraft)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const flashNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 2400)
  }

  const loadAll = useCallback(async () => {
    const [statsRes, listRes, settingsRes] = await Promise.all([
      api.getMemoryStats(),
      api.listMemories(typeFilter || undefined, 100),
      api.getMemorySettings(),
    ])
    if (statsRes.status === 'ok' && statsRes.data) setStats(statsRes.data)
    if (listRes.status === 'ok' && Array.isArray(listRes.data)) {
      setMemories(listRes.data)
    } else if (listRes.status === 'error') {
      setError(listRes.message || '加载记忆失败')
    }
    if (settingsRes.status === 'ok' && settingsRes.data) setSettings(settingsRes.data)
  }, [typeFilter])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const selectedMemory = useMemo(
    () => memories.find((m) => m.id === selectedId) || null,
    [memories, selectedId]
  )

  useEffect(() => {
    if (selectedMemory) {
      setEditing(null)
      setEditingDraft({
        content: selectedMemory.content,
        type: (selectedMemory.type as DraftMemory['type']) || 'semantic',
        importance: selectedMemory.importance ?? 0.5,
      })
    }
  }, [selectedMemory])

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([])
      return
    }
    setSearching(true)
    const res = await api.searchMemories(searchQuery.trim(), 10)
    setSearching(false)
    if (res.status === 'ok' && Array.isArray(res.data)) {
      setSearchResults(res.data)
    } else {
      setError(res.message || '搜索失败')
    }
  }

  const handleCreate = async () => {
    if (!draft.content.trim()) {
      setError('请填写记忆内容')
      return
    }
    const res = await api.createMemory(draft)
    if (res.status === 'ok') {
      setDraft(emptyDraft)
      flashNotice('已创建记忆')
      await loadAll()
    } else {
      setError(res.message || '创建失败')
    }
  }

  const handleUpdate = async () => {
    if (!selectedMemory) return
    const res = await api.updateMemory(selectedMemory.id, editingDraft)
    if (res.status === 'ok') {
      flashNotice('已更新记忆')
      setEditing(null)
      await loadAll()
    } else {
      setError(res.message || '更新失败')
    }
  }

  const handleDelete = async () => {
    if (!selectedMemory) return
    const ok = window.confirm('确认删除该条记忆？')
    if (!ok) return
    const res = await api.deleteMemory(selectedMemory.id)
    if (res.status === 'ok') {
      setSelectedId(null)
      flashNotice('已删除记忆')
      await loadAll()
    } else {
      setError(res.message || '删除失败')
    }
  }

  const handleAdvanceCycle = async () => {
    const ok = window.confirm(
      '执行后将依据当前阈值与遗忘周期触发一次遗忘判断，可能减少记忆数量。继续？'
    )
    if (!ok) return
    const res = await api.forgetMemories()
    if (res.status === 'ok') {
      flashNotice(`已遗忘 ${res.data?.forgotten ?? 0} 条记忆`)
      await loadAll()
    } else {
      setError(res.message || '触发失败')
    }
  }

  const handleConsolidate = async () => {
    const res = await api.consolidateMemories()
    if (res.status === 'ok') {
      flashNotice('已巩固记忆')
      await loadAll()
    } else {
      setError(res.message || '巩固失败')
    }
  }

  const handleSaveSettings = async () => {
    if (!settings) return
    const res = await api.updateMemorySettings({
      forget_after_days: settings.forget_after_days,
      forget_min_importance: settings.forget_min_importance,
      consolidation_threshold: settings.consolidation_threshold,
      auto_reflection_enabled: settings.auto_reflection_enabled,
      reflection_min_turns: settings.reflection_min_turns,
      recall_max_results: settings.recall_max_results,
      recall_score_threshold: settings.recall_score_threshold,
    })
    if (res.status === 'ok' && res.data) {
      setSettings(res.data)
      flashNotice('已保存设置')
    } else {
      setError(res.message || '保存设置失败')
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">记忆</h1>
          <div className="page__subtitle">
            管理与设置同页。全局记忆可被全局召回，但不等同于工作区文件授权。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" onClick={loadAll}>
            刷新
          </button>
          <button type="button" onClick={handleConsolidate}>
            巩固相似记忆
          </button>
          <button type="button" className="btn-danger" onClick={handleAdvanceCycle}>
            进入下一格遗忘周期
          </button>
        </div>
      </div>

      <div className="memory-banner">
        全局记忆按检索分数注入到每次推理；它不会替代工作区文件读取，工作区文件的访问仍需在工作区页授权。
      </div>

      {error && (
        <div className="alert alert--error">
          <span style={{ flex: 1 }}>{error}</span>
          <button className="btn-xs" onClick={() => setError('')}>关闭</button>
        </div>
      )}
      {notice && <div className="alert alert--success">{notice}</div>}

      <div className="memory-stats">
        <div className="memory-stat">
          <div className="memory-stat__label">总数</div>
          <div className="memory-stat__value">{stats?.total ?? stats?.total_memories ?? '—'}</div>
        </div>
        <div className="memory-stat">
          <div className="memory-stat__label">情景</div>
          <div className="memory-stat__value">{stats?.by_type?.episodic ?? 0}</div>
        </div>
        <div className="memory-stat">
          <div className="memory-stat__label">语义</div>
          <div className="memory-stat__value">{stats?.by_type?.semantic ?? 0}</div>
        </div>
        <div className="memory-stat">
          <div className="memory-stat__label">程序</div>
          <div className="memory-stat__value">{stats?.by_type?.procedural ?? 0}</div>
        </div>
      </div>

      <section className="memory-search">
        <span style={{ fontWeight: 600, fontSize: 13 }}>语义检索</span>
        <div className="memory-search__row">
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="输入查询，按相关度返回 Top 10"
            onKeyDown={(event) => {
              if (event.key === 'Enter') handleSearch()
            }}
          />
          <button
            type="button"
            className="btn-primary"
            disabled={searching}
            onClick={handleSearch}
          >
            {searching ? '检索中…' : '检索'}
          </button>
        </div>
        {searchResults.length > 0 && (
          <div className="memory-search__results">
            {searchResults.map((memory) => (
              <div className="memory-search__result" key={memory.id}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <strong>{TYPE_LABEL[memory.type] || memory.type}</strong>
                  <span className="text-muted" style={{ fontSize: 11.5 }}>
                    分数 {memory.retrieval?.score?.toFixed(3) ?? '—'} · 重要性{' '}
                    {Math.round((memory.importance ?? 0) * 100)}%
                  </span>
                </div>
                <div style={{ marginTop: 4 }}>{memory.content}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="memory-shell">
        {/* 列表 */}
        <aside className="memory-list-pane">
          <div className="memory-list-pane__header">
            <span style={{ fontWeight: 600 }}>记忆列表</span>
            <span className="text-muted">{memories.length} 项</span>
          </div>
          <div className="memory-list-pane__filters">
            {TYPE_OPTIONS.map((option) => (
              <button
                key={option || 'all'}
                type="button"
                className={`btn-xs ${typeFilter === option ? 'btn-primary' : ''}`}
                onClick={() => setTypeFilter(option)}
              >
                {option ? TYPE_LABEL[option] : '全部'}
              </button>
            ))}
          </div>
          <div className="memory-list-pane__items">
            {memories.length === 0 ? (
              <div className="empty-state">
                <span>尚无记忆</span>
              </div>
            ) : (
              memories.map((memory) => (
                <button
                  key={memory.id}
                  type="button"
                  className={`memory-row ${
                    selectedId === memory.id ? 'memory-row--active' : ''
                  }`}
                  onClick={() => setSelectedId(memory.id)}
                >
                  <span className="memory-row__title">
                    {memory.content.slice(0, 80)}
                  </span>
                  <span className="memory-row__kind">
                    {TYPE_LABEL[memory.type] || memory.type}
                  </span>
                  <span className="memory-row__sub">
                    <span>重要性 {Math.round((memory.importance ?? 0) * 100)}%</span>
                    <span>使用 {memory.access_count ?? 0} 次</span>
                    <span>{formatDateTime(memory.created_at)}</span>
                  </span>
                </button>
              ))
            )}
          </div>
        </aside>

        {/* 详情 + 创建 */}
        <div className="memory-detail">
          {selectedMemory ? (
            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">记忆详情</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  {!editing ? (
                    <>
                      <button
                        type="button"
                        className="btn-sm"
                        onClick={() => setEditing(selectedMemory)}
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        className="btn-danger btn-sm"
                        onClick={handleDelete}
                      >
                        删除
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn-sm"
                        onClick={() => setEditing(null)}
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        className="btn-primary btn-sm"
                        onClick={handleUpdate}
                      >
                        保存
                      </button>
                    </>
                  )}
                </div>
              </header>
              <div className="console-card__body">
                {editing ? (
                  <div className="memory-form">
                    <div className="memory-form__field">
                      <label>内容</label>
                      <textarea
                        rows={6}
                        value={editingDraft.content}
                        onChange={(event) =>
                          setEditingDraft({
                            ...editingDraft,
                            content: event.target.value,
                          })
                        }
                      />
                    </div>
                    <div className="memory-form__row">
                      <div className="memory-form__field">
                        <label>类型</label>
                        <select
                          value={editingDraft.type}
                          onChange={(event) =>
                            setEditingDraft({
                              ...editingDraft,
                              type: event.target.value as DraftMemory['type'],
                            })
                          }
                        >
                          <option value="episodic">情景</option>
                          <option value="semantic">语义</option>
                          <option value="procedural">程序</option>
                        </select>
                      </div>
                      <div className="memory-form__field">
                        <label>重要性 (0–1)</label>
                        <input
                          type="number"
                          step={0.1}
                          min={0}
                          max={1}
                          value={editingDraft.importance}
                          onChange={(event) =>
                            setEditingDraft({
                              ...editingDraft,
                              importance: Number(event.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="memory-form__field">
                        <label>访问统计</label>
                        <input
                          type="text"
                          value={`${selectedMemory.access_count ?? 0} 次`}
                          disabled
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <pre style={{ marginBottom: 12 }}>{selectedMemory.content}</pre>
                    <dl className="memory-meta-grid">
                      <div>
                        <dt>类型</dt>
                        <dd>{TYPE_LABEL[selectedMemory.type] || selectedMemory.type}</dd>
                      </div>
                      <div>
                        <dt>重要性</dt>
                        <dd>{Math.round((selectedMemory.importance ?? 0) * 100)}%</dd>
                      </div>
                      <div>
                        <dt>访问次数</dt>
                        <dd>{selectedMemory.access_count ?? 0}</dd>
                      </div>
                      <div>
                        <dt>创建时间</dt>
                        <dd>{formatDateTime(selectedMemory.created_at)}</dd>
                      </div>
                      <div>
                        <dt>最后访问</dt>
                        <dd>{formatDateTime(selectedMemory.last_accessed)}</dd>
                      </div>
                      <div>
                        <dt>记忆 ID</dt>
                        <dd className="text-mono" style={{ fontSize: 11 }}>
                          {selectedMemory.id}
                        </dd>
                      </div>
                    </dl>
                  </>
                )}
              </div>
            </section>
          ) : (
            <section className="console-card">
              <div className="console-card__body">
                <div className="empty-state">
                  <strong>请选择一条记忆</strong>
                  <span>左侧列表显示按时间倒序的记忆。</span>
                </div>
              </div>
            </section>
          )}

          {/* 创建 */}
          <section className="console-card">
            <header className="console-card__header">
              <span className="console-card__title">新建记忆</span>
            </header>
            <div className="console-card__body">
              <div className="memory-form">
                <div className="memory-form__field">
                  <label>内容</label>
                  <textarea
                    rows={4}
                    value={draft.content}
                    onChange={(event) =>
                      setDraft({ ...draft, content: event.target.value })
                    }
                    placeholder="例如：用户偏好简洁回复，避免冗长引言。"
                  />
                </div>
                <div className="memory-form__row">
                  <div className="memory-form__field">
                    <label>类型</label>
                    <select
                      value={draft.type}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          type: event.target.value as DraftMemory['type'],
                        })
                      }
                    >
                      <option value="episodic">情景</option>
                      <option value="semantic">语义</option>
                      <option value="procedural">程序</option>
                    </select>
                  </div>
                  <div className="memory-form__field">
                    <label>重要性 (0–1)</label>
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      max={1}
                      value={draft.importance}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          importance: Number(event.target.value),
                        })
                      }
                    />
                  </div>
                  <div className="memory-form__field">
                    <label>&nbsp;</label>
                    <button
                      type="button"
                      className="btn-primary"
                      onClick={handleCreate}
                    >
                      创建
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* 设置 */}
          {settings && (
            <section className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">记忆设置</span>
                <button type="button" className="btn-primary btn-sm" onClick={handleSaveSettings}>
                  保存设置
                </button>
              </header>
              <div className="console-card__body">
                <div className="memory-form">
                  <div className="memory-form__row">
                    <div className="memory-form__field">
                      <label>遗忘周期（天）</label>
                      <input
                        type="number"
                        min={1}
                        max={3650}
                        value={settings.forget_after_days}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            forget_after_days: Number(event.target.value) || 1,
                          })
                        }
                      />
                      <span className="text-muted" style={{ fontSize: 11 }}>
                        默认 1 天，超过该时间且重要性低的记忆会被遗忘。
                      </span>
                    </div>
                    <div className="memory-form__field">
                      <label>遗忘最低重要性</label>
                      <input
                        type="number"
                        step={0.05}
                        min={0}
                        max={1}
                        value={settings.forget_min_importance}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            forget_min_importance: Number(event.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="memory-form__field">
                      <label>巩固阈值</label>
                      <input
                        type="number"
                        step={0.05}
                        min={0}
                        max={1}
                        value={settings.consolidation_threshold}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            consolidation_threshold: Number(event.target.value),
                          })
                        }
                      />
                    </div>
                  </div>
                  <div className="memory-form__row">
                    <div className="memory-form__field">
                      <label>召回 Top-K</label>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={settings.recall_max_results}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            recall_max_results: Number(event.target.value) || 1,
                          })
                        }
                      />
                    </div>
                    <div className="memory-form__field">
                      <label>召回阈值</label>
                      <input
                        type="number"
                        step={0.05}
                        min={0}
                        max={1}
                        value={settings.recall_score_threshold}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            recall_score_threshold: Number(event.target.value),
                          })
                        }
                      />
                    </div>
                    <div className="memory-form__field">
                      <label>反思最小轮数</label>
                      <input
                        type="number"
                        min={1}
                        max={20}
                        value={settings.reflection_min_turns}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            reflection_min_turns: Number(event.target.value) || 1,
                          })
                        }
                      />
                    </div>
                  </div>
                  <label
                    style={{
                      display: 'flex',
                      gap: 8,
                      alignItems: 'center',
                      fontSize: 12.5,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={settings.auto_reflection_enabled}
                      onChange={(event) =>
                        setSettings({
                          ...settings,
                          auto_reflection_enabled: event.target.checked,
                        })
                      }
                    />
                    <span>启用自动反思（对话累计达到最小轮数后形成长期记忆）</span>
                  </label>
                </div>
                <div
                  className="text-muted"
                  style={{ marginTop: 8, fontSize: 11.5 }}
                >
                  存储后端：{settings.backend} · 集合：{settings.collection_name} · 状态：
                  {settings.status?.initialized ? '已就绪' : '未就绪'}
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
