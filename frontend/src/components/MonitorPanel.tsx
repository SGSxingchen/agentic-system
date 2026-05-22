import { useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type { Task, WSEvent } from '../types'
import './MonitorPanel.css'

const FILTERS: Array<{ value: string; label: string; matches: (event: WSEvent) => boolean }> = [
  { value: 'all', label: '全部', matches: () => true },
  {
    value: 'run',
    label: '运行',
    matches: (event) => {
      const type = event.event_type || event.type || ''
      return type.startsWith('agent_run') || type === 'agent_progress'
    },
  },
  {
    value: 'tool',
    label: '工具',
    matches: (event) => {
      const type = event.event_type || event.type || ''
      return type.includes('tool') || Boolean(event.data?.tool)
    },
  },
  {
    value: 'memory',
    label: '记忆',
    matches: (event) => {
      const type = event.event_type || event.type || ''
      return type.includes('memory') || type === 'reflection_generated'
    },
  },
  {
    value: 'error',
    label: '错误',
    matches: (event) => {
      const type = event.event_type || event.type || ''
      const detail = JSON.stringify(event.data || {}).toLowerCase()
      return (
        type.includes('error') ||
        type.includes('failed') ||
        detail.includes('"error"')
      )
    },
  },
]

const ACTIVE_STATUSES = new Set(['running', 'paused'])

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

function formatDuration(start?: string | null) {
  if (!start) return '—'
  const s = new Date(start).getTime()
  if (Number.isNaN(s)) return '—'
  const ms = Date.now() - s
  if (ms < 0) return '—'
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  if (ms < 3600_000) return `${Math.round(ms / 60_000)}m`
  return `${Math.round(ms / 3600_000)}h`
}

function formatTimeShort(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function mergeRunEvent(runs: Task[], event: WSEvent): Task[] {
  const eventType = event.event_type || event.type || ''
  if (
    !eventType.startsWith('agent_run') &&
    eventType !== 'agent_progress'
  ) {
    return runs
  }

  const data = event.data || {}
  const runId = data.run_id || data.task_id
  if (!runId) return runs

  const now = event.timestamp || new Date().toISOString()
  const status = data.status || (eventType === 'agent_run_started' ? 'running' : undefined)
  const nextProgress = {
    activity: data.activity || data.event_type || '',
    current_step: data.current_step || data.event_type || null,
    last_tool: data.tool || null,
  }

  const existing = runs.find((run) => run.id === runId || run.run_id === runId || run.task_id === runId)
  const merged: Task = {
    ...(existing || {
      id: runId,
      task_id: runId,
      run_id: runId,
      type: 'agent_run',
      requirement: data.goal || '',
      goal: data.goal || '',
      status: 'running',
      created_at: now,
    }),
    id: existing?.id || runId,
    task_id: existing?.task_id || runId,
    run_id: existing?.run_id || runId,
    agent_name: data.agent || existing?.agent_name || existing?.agent || null,
    agent: data.agent || existing?.agent || existing?.agent_name || undefined,
    workspace_id: data.workspace_id || existing?.workspace_id || null,
    session_id: data.session_id || existing?.session_id || null,
    auto_memory: typeof data.auto_memory === 'boolean' ? data.auto_memory : existing?.auto_memory,
    status: (status || existing?.status || 'running') as Task['status'],
    requirement: existing?.requirement || data.goal || '',
    goal: existing?.goal || data.goal || '',
    updated_at: now,
    progress: {
      tool_count: existing?.progress?.tool_count || 0,
      total_tokens: existing?.progress?.total_tokens || 0,
      ...existing?.progress,
      ...Object.fromEntries(
        Object.entries(nextProgress).filter(([, value]) => value !== '' && value !== null)
      ),
    },
  }

  if (eventType === 'agent_run_completed' || eventType === 'agent_run_failed' || eventType === 'agent_run_cancelled') {
    merged.ended_at = now
  }

  return [merged, ...runs.filter((run) => run.id !== runId && run.run_id !== runId && run.task_id !== runId)]
}

export function MonitorPanel() {
  const { state, dispatch } = useAppStore()
  const [filter, setFilter] = useState('all')
  const [runs, setRuns] = useState<Task[]>([])

  useEffect(() => {
    const load = async () => {
      const res = await api.getRuns()
      if (res.status === 'ok' && Array.isArray(res.data)) setRuns(res.data)
    }
    load()
    const t = window.setInterval(load, 4000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    const latest = state.wsEvents[state.wsEvents.length - 1]
    if (!latest) return
    setRuns((prev) => mergeRunEvent(prev, latest))
  }, [state.wsEvents])

  const grouped = useMemo(() => {
    const map = new Map<string, Task[]>()
    runs
      .filter((run) => ACTIVE_STATUSES.has(run.status))
      .forEach((run) => {
        const key = run.agent_name || run.agent || '未指定'
        const list = map.get(key) || []
        list.push(run)
        map.set(key, list)
      })
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }, [runs])

  const matcher = useMemo(
    () => FILTERS.find((f) => f.value === filter)?.matches || (() => true),
    [filter]
  )

  const filteredEvents = useMemo(
    () => state.wsEvents.filter(matcher).slice(-200).reverse(),
    [state.wsEvents, matcher]
  )

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">监控</h1>
          <div className="page__subtitle">
            按智能体分组查看活跃运行；事件来自 WebSocket 实时通道。
          </div>
        </div>
        <div className="page__actions">
          <button
            type="button"
            onClick={() => dispatch({ type: 'CLEAR_WS_EVENTS' })}
          >
            清空事件
          </button>
        </div>
      </div>

      <div className="monitor-shell">
        <section className="console-card">
          <header className="console-card__header">
            <span className="console-card__title">活跃智能体</span>
            <span className="text-muted">
              {grouped.length} 个智能体 ·
              {' '}
              {grouped.reduce((acc, [, list]) => acc + list.length, 0)} 个运行
            </span>
          </header>
          <div className="console-card__body">
            {grouped.length === 0 ? (
              <div className="empty-state">
                <strong>暂无活跃运行</strong>
                <span>新创建的运行将按智能体分组显示。</span>
              </div>
            ) : (
              <div className="monitor-agents">
                {grouped.map(([agentName, runList]) => (
                  <div key={agentName} className="monitor-agent-card">
                    <div className="monitor-agent-card__head">
                      <span className="monitor-agent-card__name">{agentName}</span>
                      <span className="monitor-agent-card__count">
                        {runList.length} 个运行
                      </span>
                    </div>
                    <div className="monitor-agent-card__body">
                      {runList.map((run) => (
                        <div className="monitor-run-pill" key={run.id}>
                          <div className="monitor-run-pill__top">
                            <span className={statusPillClass(run.status)}>
                              {STATUS_LABEL[run.status] || run.status}
                            </span>
                            <span style={{ fontWeight: 500 }}>
                              {run.requirement?.slice(0, 40) ||
                                run.goal?.slice(0, 40) ||
                                run.id.slice(0, 8)}
                            </span>
                          </div>
                          <span className="text-muted text-mono" style={{ fontSize: 11 }}>
                            {formatDuration(run.created_at)}
                          </span>
                          <div className="monitor-run-pill__sub">
                            {run.progress?.activity || '等待事件…'}
                            {run.progress?.last_tool
                              ? ` · 最近工具 ${run.progress.last_tool}`
                              : ''}
                          </div>
                          <div className="monitor-run-pill__sub">
                            工作区 {run.workspace_id || '未指定'}
                            {typeof run.progress?.memory_count === 'number'
                              ? ` · 记忆 ${run.progress.memory_count} 条`
                              : ''}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="monitor-events">
          <header className="monitor-events__header">
            <span className="console-card__title">事件流</span>
            <div className="monitor-events__filters">
              {FILTERS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`btn-xs ${
                    filter === option.value ? 'btn-primary' : ''
                  }`}
                  onClick={() => setFilter(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </header>
          <div className="monitor-events__list">
            {filteredEvents.length === 0 ? (
              <div className="empty-state">
                <span>暂无匹配事件</span>
              </div>
            ) : (
              filteredEvents.map((event, index) => (
                <div className="monitor-event-row" key={`${event.timestamp}-${index}`}>
                  <span className="monitor-event-row__time">
                    {formatTimeShort(event.timestamp)}
                  </span>
                  <span className="monitor-event-row__type">
                    {event.event_type || event.type || '—'}
                  </span>
                  <span className="monitor-event-row__detail">
                    {(() => {
                      try {
                        return typeof event.data === 'string'
                          ? event.data
                          : JSON.stringify(event.data).slice(0, 200)
                      } catch {
                        return ''
                      }
                    })()}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
