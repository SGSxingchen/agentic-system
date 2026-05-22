import { useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type { Task } from '../types'
import './OverviewPanel.css'

function formatTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function statusPillClass(status?: string) {
  switch (status) {
    case 'running':
    case 'pending':
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

function statusLabel(status?: string) {
  const map: Record<string, string> = {
    pending: '排队中',
    running: '运行中',
    paused: '暂停',
    completed: '已完成',
    failed: '失败',
    killed: '已取消',
  }
  return map[status || ''] || status || '—'
}

export function OverviewPanel() {
  const { state } = useAppStore()
  const [runs, setRuns] = useState<Task[]>([])
  const [loadingRuns, setLoadingRuns] = useState(false)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoadingRuns(true)
      const res = await api.getRuns()
      if (cancelled) return
      if (res.status === 'ok' && Array.isArray(res.data)) {
        setRuns(res.data)
      }
      setLoadingRuns(false)
    }

    load()
    const t = window.setInterval(load, 5_000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [])

  const activeRuns = useMemo(
    () => runs.filter((r) => r.status === 'running' || r.status === 'paused'),
    [runs]
  )

  const recentRuns = useMemo(
    () =>
      [...runs]
        .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
        .slice(0, 6),
    [runs]
  )

  const recentEvents = useMemo(() => state.wsEvents.slice(-12).reverse(), [state.wsEvents])

  const health = state.health
  const selected = state.selectedWorkspace
  const selectedDetail = state.workspaces.find((w) => w.id === selected?.id)

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">总览</h1>
          <div className="page__subtitle">
            后端状态、活跃运行与最近事件，一屏可扫描。
          </div>
        </div>
      </div>

      <div className="overview-grid">
        <div className="overview-stat">
          <span className="overview-stat__label">后端服务</span>
          <span className="overview-stat__value">
            <span className={`pill ${health?.status === 'ok' ? 'pill--success' : 'pill--warning'}`}>
              {health?.status === 'ok' ? '运行中' : health?.status || '未知'}
            </span>
          </span>
          <span className="overview-stat__hint">
            版本 {health?.version || '—'}
          </span>
        </div>

        <div className="overview-stat">
          <span className="overview-stat__label">实时通道</span>
          <span className="overview-stat__value">
            <span className={`pill ${state.connected ? 'pill--success' : 'pill--danger'}`}>
              {state.connected ? '已连接' : '已断开'}
            </span>
          </span>
          <span className="overview-stat__hint">
            消息总线 {health?.bus_running ? '在线' : '离线'}
          </span>
        </div>

        <div className="overview-stat">
          <span className="overview-stat__label">活跃运行</span>
          <span className="overview-stat__value">{activeRuns.length}</span>
          <span className="overview-stat__hint">
            历史共 {runs.length} 个 Run
          </span>
        </div>

        <div className="overview-stat">
          <span className="overview-stat__label">当前工作区</span>
          <span className="overview-stat__value" style={{ fontSize: 14, fontWeight: 600 }}>
            {selected?.name || '未选择'}
          </span>
          <span className="overview-stat__hint">
            {selected
              ? selectedDetail?.metadata?.file_count != null
                ? `${selectedDetail.metadata.file_count} 个文件`
                : '点击右上角切换'
              : '前往工作区页选择或导入'}
          </span>
        </div>
      </div>

      <div className="overview-columns">
        <section className="console-card">
          <header className="console-card__header">
            <span className="console-card__title">最近运行</span>
            <span className="text-muted">{loadingRuns ? '刷新中…' : `${runs.length} 项`}</span>
          </header>
          <div className="console-card__body console-card__body--flush overview-runs">
            {recentRuns.length === 0 ? (
              <div className="empty-state">
                <strong>暂无运行</strong>
                <span>从「运行」页面创建一个 Agent Run。</span>
              </div>
            ) : (
              recentRuns.map((run) => (
                <div className="overview-run" key={run.id}>
                  <div>
                    <div className="overview-run__top">
                      <span className={statusPillClass(run.status)}>{statusLabel(run.status)}</span>
                      <span style={{ color: 'var(--color-text-primary)', fontWeight: 500 }}>
                        {run.agent_name || run.agent || run.requirement?.slice(0, 32) || run.id.slice(0, 8)}
                      </span>
                    </div>
                    <div className="overview-run__sub">
                      {run.workspace_id ? `工作区 ${run.workspace_id}` : '默认工作区'} · {formatTime(run.created_at)}
                    </div>
                  </div>
                  <span className="text-muted text-mono" style={{ fontSize: 11.5 }}>
                    {run.id.slice(0, 8)}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="console-card">
          <header className="console-card__header">
            <span className="console-card__title">最近事件</span>
            <span className="text-muted">{state.wsEvents.length} 条</span>
          </header>
          <div className="console-card__body console-card__body--flush overview-events">
            {recentEvents.length === 0 ? (
              <div className="empty-state">
                <strong>暂无事件</strong>
                <span>WebSocket 事件会在此实时追加。</span>
              </div>
            ) : (
              recentEvents.map((event, index) => (
                <div className="overview-event" key={`${event.timestamp}-${index}`}>
                  <span className="overview-event__time">{formatTime(event.timestamp)}</span>
                  <span className="overview-event__type">{event.event_type || event.type}</span>
                  <span className="overview-event__detail">
                    {event.data
                      ? typeof event.data === 'string'
                        ? event.data
                        : JSON.stringify(event.data).slice(0, 100)
                      : '—'}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <section className="console-card">
        <header className="console-card__header">
          <span className="console-card__title">系统信息</span>
        </header>
        <div className="overview-summary">
          <div className="overview-summary__row">
            <span className="overview-summary__label">智能体加载</span>
            <span className="overview-summary__value">{health?.agent_loaded ? '已加载' : '未就绪'}</span>
          </div>
          <div className="overview-summary__row">
            <span className="overview-summary__label">记忆系统</span>
            <span className="overview-summary__value">{health?.memory_initialized ? '已初始化' : '未初始化'}</span>
          </div>
          <div className="overview-summary__row">
            <span className="overview-summary__label">工作区数量</span>
            <span className="overview-summary__value">{state.workspaces.length}</span>
          </div>
          {health?.agents && (
            <div className="overview-summary__row">
              <span className="overview-summary__label">注册智能体</span>
              <span className="overview-summary__value">
                {Object.keys(health.agents).length} 个
              </span>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
