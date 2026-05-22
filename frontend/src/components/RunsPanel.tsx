import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type { AgentInfo, RunEvent, Task } from '../types'
import './RunsPanel.css'

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: '', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'paused', label: '暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'killed', label: '已取消' },
]

const STATUS_LABEL: Record<string, string> = {
  pending: '排队',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  killed: '已取消',
}

function statusPillClass(status?: string) {
  switch (status) {
    case 'running':
      return 'pill pill--info'
    case 'completed':
      return 'pill pill--success'
    case 'failed':
      return 'pill pill--danger'
    case 'killed':
    case 'paused':
      return 'pill pill--warning'
    default:
      return 'pill'
  }
}

function formatTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatTimeShort(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function formatDuration(start?: string | null, end?: string | null) {
  if (!start) return '—'
  const startMs = new Date(start).getTime()
  if (Number.isNaN(startMs)) return '—'
  const endMs = end ? new Date(end).getTime() : Date.now()
  if (Number.isNaN(endMs)) return '—'
  const seconds = Math.max(0, Math.round((endMs - startMs) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分 ${seconds % 60} 秒`
  return `${Math.floor(minutes / 60)} 时 ${minutes % 60} 分`
}

export function RunsPanel() {
  const { state } = useAppStore()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [runs, setRuns] = useState<Task[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [runEvents, setRunEvents] = useState<RunEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // form state
  const [formAgent, setFormAgent] = useState('')
  const [formGoal, setFormGoal] = useState('')
  const [formMode, setFormMode] = useState<'continuous' | 'once'>('continuous')
  const [formCriteria, setFormCriteria] = useState('')
  const [formMax, setFormMax] = useState(20)
  const [formAutoMemory, setFormAutoMemory] = useState(true)
  const [formWorkspace, setFormWorkspace] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api.listAgents().then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) {
        setAgents(res.data)
        if (res.data.length && !formAgent) setFormAgent(res.data[0].name)
      }
    })
  }, [])

  useEffect(() => {
    setFormWorkspace(state.selectedWorkspace?.id || '')
  }, [state.selectedWorkspace])

  const loadRuns = useCallback(async () => {
    setLoading(true)
    const res = await api.getRuns(statusFilter ? { status: statusFilter } : undefined)
    if (res.status === 'ok' && Array.isArray(res.data)) {
      setRuns(res.data)
    } else {
      setError(res.message || '加载运行失败')
    }
    setLoading(false)
  }, [statusFilter])

  useEffect(() => {
    loadRuns()
    const t = window.setInterval(loadRuns, 4000)
    return () => window.clearInterval(t)
  }, [loadRuns])

  // run detail
  useEffect(() => {
    if (!selectedRunId) {
      setRunEvents([])
      return
    }
    let cancelled = false
    const load = async () => {
      const res = await api.getRunEvents(selectedRunId)
      if (cancelled) return
      if (res.status === 'ok' && res.data?.events) {
        setRunEvents(res.data.events)
      }
    }
    load()
    const t = window.setInterval(load, 3000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [selectedRunId])

  const sortedRuns = useMemo(
    () =>
      [...runs].sort((a, b) =>
        (b.created_at || '').localeCompare(a.created_at || '')
      ),
    [runs]
  )

  const selectedRun = useMemo(
    () => runs.find((r) => r.id === selectedRunId) || null,
    [runs, selectedRunId]
  )

  const handleSubmit = async () => {
    if (!formGoal.trim()) {
      setError('请填写任务描述')
      return
    }
    if (!formAgent) {
      setError('请选择一个智能体')
      return
    }
    setSubmitting(true)
    setError('')
    const res = await api.createRun({
      goal: formGoal.trim(),
      agent_name: formAgent,
      workspace_id: formWorkspace || undefined,
      mode: formMode,
      max_iterations: Math.max(1, Math.min(formMax, 200)),
      completion_criteria: formCriteria || '',
      auto_memory: formAutoMemory,
    })
    setSubmitting(false)
    if (res.status === 'ok' && res.data) {
      setFormGoal('')
      setSelectedRunId(res.data.id)
      await loadRuns()
    } else {
      setError(res.message || '创建运行失败')
    }
  }

  const handleControl = async (runId: string, action: 'cancel') => {
    const res = await api.controlRun(runId, action)
    if (res.status !== 'ok') {
      setError(res.message || '操作失败')
    } else {
      await loadRuns()
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">运行</h1>
          <div className="page__subtitle">
            创建并管理 Agent Run。每次运行都会绑定一个智能体和工作区。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" onClick={loadRuns} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
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

      <div className="runs-shell">
        <aside className="run-form">
          <div className="run-form__title">创建运行</div>

          <div className="run-form__field">
            <label>智能体</label>
            <select
              value={formAgent}
              onChange={(event) => setFormAgent(event.target.value)}
            >
              {agents.length === 0 && <option value="">未发现智能体</option>}
              {agents.map((agent) => (
                <option key={agent.name} value={agent.name}>
                  {agent.name} — {agent.description || '无描述'}
                </option>
              ))}
            </select>
          </div>

          <div className="run-form__field">
            <label>工作区</label>
            <select
              value={formWorkspace}
              onChange={(event) => setFormWorkspace(event.target.value)}
            >
              <option value="">不绑定（运行时由智能体决定）</option>
              {state.workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
            {state.selectedWorkspace?.id &&
              formWorkspace === state.selectedWorkspace.id && (
                <span className="text-muted" style={{ fontSize: 11 }}>
                  已使用顶部选定的工作区
                </span>
              )}
          </div>

          <div className="run-form__field">
            <label>任务描述</label>
            <textarea
              value={formGoal}
              onChange={(event) => setFormGoal(event.target.value)}
              placeholder="例如：检查工作区中的文档结构，归纳每章主题。"
            />
          </div>

          <div className="run-form__row">
            <div className="run-form__field">
              <label>运行模式</label>
              <select
                value={formMode}
                onChange={(event) =>
                  setFormMode(event.target.value as 'continuous' | 'once')
                }
              >
                <option value="continuous">持续运行</option>
                <option value="once">单次执行</option>
              </select>
            </div>
            <div className="run-form__field">
              <label>最大迭代</label>
              <input
                type="number"
                min={1}
                max={200}
                value={formMax}
                onChange={(event) => setFormMax(Number(event.target.value))}
              />
            </div>
          </div>

          <div className="run-form__field">
            <label>完成标准（可选）</label>
            <input
              type="text"
              value={formCriteria}
              onChange={(event) => setFormCriteria(event.target.value)}
              placeholder="智能体据此自检是否完成"
            />
          </div>

          <label className="run-form__inline">
            <input
              type="checkbox"
              checked={formAutoMemory}
              onChange={(event) => setFormAutoMemory(event.target.checked)}
            />
            <span>自动使用并沉淀长期记忆</span>
          </label>

          <div className="run-form__actions">
            <button
              type="button"
              className="btn-primary"
              disabled={submitting}
              onClick={handleSubmit}
            >
              {submitting ? '创建中…' : '创建运行'}
            </button>
          </div>
        </aside>

        <div className="run-detail">
          <div className="runs-list">
            <div className="runs-list__header">
              <span style={{ fontWeight: 600 }}>运行列表</span>
              <div className="runs-list__filters">
                {STATUS_FILTERS.map((filter) => (
                  <button
                    key={filter.value}
                    type="button"
                    className={`btn-xs ${
                      statusFilter === filter.value ? 'btn-primary' : ''
                    }`}
                    onClick={() => setStatusFilter(filter.value)}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="runs-list__items">
              {sortedRuns.length === 0 ? (
                <div className="empty-state">
                  <strong>暂无运行</strong>
                  <span>从左侧表单创建一个 Agent Run。</span>
                </div>
              ) : (
                sortedRuns.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    className={`run-row ${
                      selectedRunId === run.id ? 'run-row--active' : ''
                    }`}
                    onClick={() => setSelectedRunId(run.id)}
                  >
                    <div className="run-row__title">
                      <span className={statusPillClass(run.status)}>
                        {STATUS_LABEL[run.status] || run.status}
                      </span>
                      <span style={{ fontWeight: 600 }}>
                        {run.agent_name || run.agent || '未指定智能体'}
                      </span>
                      <span style={{ color: 'var(--color-text-muted)' }}>
                        {run.requirement?.slice(0, 60) || run.goal?.slice(0, 60) || '—'}
                      </span>
                    </div>
                    <span
                      className="text-muted text-mono"
                      style={{ fontSize: 11.5 }}
                    >
                      {run.id.slice(0, 8)}
                    </span>
                    <div className="run-row__sub">
                      <span>创建 {formatTimeShort(run.created_at)}</span>
                      <span>耗时 {formatDuration(run.created_at, run.ended_at)}</span>
                      {run.workspace_id && <span>工作区 {run.workspace_id}</span>}
                      {run.progress?.tool_count != null && (
                        <span>工具调用 {run.progress.tool_count}</span>
                      )}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {selectedRun && (
            <div className="console-card">
              <header className="console-card__header">
                <span className="console-card__title">运行详情</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  {selectedRun.status === 'running' && (
                    <button
                      type="button"
                      className="btn-danger btn-sm"
                      onClick={() => handleControl(selectedRun.id, 'cancel')}
                    >
                      取消
                    </button>
                  )}
                </div>
              </header>
              <div className="console-card__body">
                <dl
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
                    gap: '10px 24px',
                    margin: 0,
                    fontSize: 12.5,
                  }}
                >
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      当前阶段
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {selectedRun.progress?.current_step || '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      最近活动
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {selectedRun.progress?.activity || '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      最近工具
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {selectedRun.progress?.last_tool || '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      Token 累计
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {selectedRun.progress?.total_tokens ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      智能体
                    </dt>
                    <dd style={{ margin: 0 }}>{selectedRun.agent_name || '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      工作区
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {selectedRun.workspace_id || '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      创建时间
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {formatTime(selectedRun.created_at)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted" style={{ fontSize: 11.5 }}>
                      结束时间
                    </dt>
                    <dd style={{ margin: 0 }}>
                      {formatTime(selectedRun.ended_at || undefined)}
                    </dd>
                  </div>
                </dl>
              </div>

              <header className="console-card__header">
                <span className="console-card__title">事件时间线</span>
                <span className="text-muted">{runEvents.length} 条</span>
              </header>
              <div className="run-detail__events">
                {runEvents.length === 0 ? (
                  <div className="empty-state">
                    <span>暂无事件</span>
                  </div>
                ) : (
                  runEvents.map((event, index) => (
                    <div className="run-event-row" key={index}>
                      <span className="run-event-row__time">
                        {formatTimeShort(event.ts)}
                      </span>
                      <span className="run-event-row__type">{event.type}</span>
                      <span className="run-event-row__detail">
                        {event.payload?.tool ? `${event.payload.tool}` : ''}
                        {event.payload?.error && ` 错误：${event.payload.error}`}
                        {!event.payload?.tool &&
                          !event.payload?.error &&
                          (() => {
                            try {
                              return JSON.stringify(event.payload).slice(0, 240)
                            } catch {
                              return ''
                            }
                          })()}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
