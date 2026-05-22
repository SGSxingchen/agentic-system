import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useAppStore } from '../store/appStore'
import * as api from '../api/client'
import type { WSEvent } from '../types'
import './MonitorPanel.css'

interface AgentRuntimeState {
  agent: string
  status: string
  activity: string
  currentStep?: string
  tool?: string
  taskId?: string
  runId?: string
  updatedAt?: string
  message?: string
  source: string
}

function eventName(event: WSEvent) {
  return event.event_type || event.type
}

function normalizeAgentName(data: Record<string, unknown>) {
  const value = data.agent || data.agent_name || data.name || data.target
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function pickString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function stateFromEvent(event: WSEvent): AgentRuntimeState | null {
  const data = event.data && typeof event.data === 'object' ? event.data as Record<string, unknown> : {}
  const type = eventName(event)
  const agent = normalizeAgentName(data)
  if (!agent) return null

  if (type === 'agent_status_update') {
    return {
      agent,
      status: pickString(data.status) || 'idle',
      activity: '状态更新',
      updatedAt: event.timestamp,
      source: type,
    }
  }

  if (
    type === 'agent_progress' ||
    type === 'agent_run_started' ||
    type === 'agent_run_event' ||
    type === 'agent_run_completed' ||
    type === 'agent_run_failed' ||
    type === 'agent_run_cancelled'
  ) {
    const status =
      pickString(data.status) ||
      (type === 'agent_run_completed' ? 'completed' : type === 'agent_run_failed' ? 'failed' : 'running')
    const activity =
      pickString(data.activity) ||
      pickString(data.event_type) ||
      (type === 'agent_run_started' ? 'started' : type.replace(/^agent_/, ''))

    return {
      agent,
      status,
      activity,
      currentStep: pickString(data.current_step),
      tool: pickString(data.tool),
      taskId: pickString(data.task_id),
      runId: pickString(data.run_id),
      message: pickString(data.message) || pickString(data.error),
      updatedAt: event.timestamp,
      source: type,
    }
  }

  return null
}

function statusClass(status: string) {
  if (['running', 'busy'].includes(status)) return 'running'
  if (['completed', 'success', 'idle'].includes(status)) return 'healthy'
  if (['failed', 'error', 'killed'].includes(status)) return 'danger'
  return 'muted'
}

function formatTime(value?: string) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString()
}

export function MonitorPanel() {
  const { state, dispatch } = useAppStore()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const eventListRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const fetchRuntime = useCallback(async () => {
    const [healthRes, agentsRes] = await Promise.all([
      api.getHealth(),
      api.listAgents(),
    ])

    if (healthRes.status === 'ok' && healthRes.data) {
      dispatch({ type: 'SET_HEALTH', payload: healthRes.data })
      setError(null)
    } else {
      setError(healthRes.message || '无法连接到后端服务')
    }

    if (agentsRes.status === 'ok' && agentsRes.data) {
      dispatch({ type: 'SET_AGENTS', payload: agentsRes.data })
    }

    setLoading(false)
  }, [dispatch])

  useEffect(() => {
    fetchRuntime()
    const timer = setInterval(fetchRuntime, 5000)
    return () => clearInterval(timer)
  }, [fetchRuntime])

  useEffect(() => {
    if (autoScroll && eventListRef.current) {
      eventListRef.current.scrollTop = eventListRef.current.scrollHeight
    }
  }, [state.wsEvents, autoScroll])

  const agentCards = useMemo(() => {
    const byAgent = new Map<string, AgentRuntimeState>()

    for (const agent of state.agents) {
      byAgent.set(agent.name, {
        agent: agent.name,
        status: agent.status,
        activity: '空闲',
        updatedAt: undefined,
        source: 'agents_api',
      })
    }

    if (state.health?.agents) {
      for (const [agent, status] of Object.entries(state.health.agents)) {
        const existing = byAgent.get(agent)
        byAgent.set(agent, {
          agent,
          status,
          activity: existing?.activity || '空闲',
          updatedAt: existing?.updatedAt,
          source: existing?.source || 'health_api',
        })
      }
    }

    for (const event of state.wsEvents) {
      const next = stateFromEvent(event)
      if (!next) continue
      byAgent.set(next.agent, {
        ...byAgent.get(next.agent),
        ...next,
      })
    }

    return Array.from(byAgent.values()).sort((a, b) => a.agent.localeCompare(b.agent))
  }, [state.agents, state.health, state.wsEvents])

  const handleEventScroll = () => {
    if (eventListRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = eventListRef.current
      setAutoScroll(scrollHeight - scrollTop - clientHeight < 50)
    }
  }

  const health = state.health
  const isBackendDown = !health && !loading

  const healthDotColor = (ok: boolean | undefined) => {
    if (isBackendDown) return '#9CA3AF'
    return ok ? '#16A34A' : '#DC2626'
  }

  return (
    <div className="monitor-panel">
      <div className="panel-header">
        <h2>系统监控</h2>
        <button className="refresh-btn" onClick={fetchRuntime}>
          刷新
        </button>
      </div>

      {error && <div className="monitor-error">{error}</div>}

      <div className="health-cards">
        <div className={`health-card ${health ? 'healthy' : 'unhealthy'}`}>
          <div className="health-card-icon" style={{ backgroundColor: healthDotColor(!!health) }} />
          <div className="health-card-info">
            <div className="health-card-label">系统状态</div>
            <div className="health-card-value">{loading ? '检查中...' : health ? '运行中' : '离线'}</div>
          </div>
        </div>

        <div className={`health-card ${health?.bus_running ? 'healthy' : 'unhealthy'}`}>
          <div className="health-card-icon" style={{ backgroundColor: healthDotColor(health?.bus_running) }} />
          <div className="health-card-info">
            <div className="health-card-label">事件总线</div>
            <div className="health-card-value">{isBackendDown ? '未知' : health?.bus_running ? '运行中' : '未运行'}</div>
          </div>
        </div>

        <div className={`health-card ${health?.agent_loaded ? 'healthy' : 'unhealthy'}`}>
          <div className="health-card-icon" style={{ backgroundColor: healthDotColor(health?.agent_loaded) }} />
          <div className="health-card-info">
              <div className="health-card-label">智能体引擎</div>
            <div className="health-card-value">{isBackendDown ? '未知' : health?.agent_loaded ? '已加载' : '未加载'}</div>
          </div>
        </div>

        <div className={`health-card ${health?.memory_initialized ? 'healthy' : 'unhealthy'}`}>
          <div className="health-card-icon" style={{ backgroundColor: healthDotColor(health?.memory_initialized) }} />
          <div className="health-card-info">
            <div className="health-card-label">记忆系统</div>
            <div className="health-card-value">{isBackendDown ? '未知' : health?.memory_initialized ? '已初始化' : '未初始化'}</div>
          </div>
        </div>
      </div>

      <div className="monitor-section">
        <h3>连接信息</h3>
        <div className="info-grid">
          <div className="info-item">
            <span className="info-label">WebSocket</span>
            <span className={`info-value ${state.connected ? 'text-success' : 'text-danger'}`}>
              {state.connected ? '已连接' : '未连接'}
            </span>
          </div>
          <div className="info-item">
            <span className="info-label">消息总数</span>
            <span className="info-value">{state.messages.length}</span>
          </div>
          <div className="info-item">
            <span className="info-label">事件总数</span>
            <span className="info-value">{state.wsEvents.length}</span>
          </div>
          <div className="info-item">
            <span className="info-label">智能体数</span>
            <span className="info-value">{agentCards.length}</span>
          </div>
          {health?.version && (
            <div className="info-item">
              <span className="info-label">版本</span>
              <span className="info-value">{health.version}</span>
            </div>
          )}
        </div>
      </div>

      <div className="monitor-section">
          <h3>智能体实时进展</h3>
        {agentCards.length > 0 ? (
          <div className="agent-progress-grid">
            {agentCards.map((agent) => (
              <div key={agent.agent} className={`agent-progress-card ${statusClass(agent.status)}`}>
                <div className="agent-progress-card__header">
                  <strong>{agent.agent}</strong>
                  <span>{agent.status}</span>
                </div>
                <div className="agent-progress-card__activity">{agent.activity || '空闲'}</div>
                <div className="agent-progress-card__meta">
                  <span>步骤</span>
                  <b>{agent.currentStep || '-'}</b>
                  <span>工具</span>
                  <b>{agent.tool || '-'}</b>
                  <span>任务</span>
                  <b>{agent.taskId || agent.runId || '-'}</b>
                  <span>更新</span>
                  <b>{formatTime(agent.updatedAt)}</b>
                </div>
                {agent.message && <p className="agent-progress-card__message">{agent.message}</p>}
              </div>
            ))}
          </div>
        ) : (
          <div className="event-stream-empty event-stream-empty--compact">
            等待 Agent 列表或实时进展事件...
          </div>
        )}
      </div>

      <div className="monitor-section event-stream-section">
        <div className="section-header">
          <h3>实时事件流</h3>
          <div className="event-stream-actions">
            <span className="event-count">{state.wsEvents.length} 条事件</span>
            {!autoScroll && (
              <button
                className="clear-events-btn"
                onClick={() => {
                  setAutoScroll(true)
                  if (eventListRef.current) {
                    eventListRef.current.scrollTop = eventListRef.current.scrollHeight
                  }
                }}
              >
                ↓ 滚动到底部
              </button>
            )}
            <button className="clear-events-btn" onClick={() => dispatch({ type: 'CLEAR_WS_EVENTS' })}>
              清空
            </button>
          </div>
        </div>

        <div className="event-stream" ref={eventListRef} onScroll={handleEventScroll}>
          {state.wsEvents.length === 0 ? (
            <div className="event-stream-empty">
              <p>{state.connected ? '等待系统事件...' : '未连接 WebSocket，请确认后端服务已启动'}</p>
            </div>
          ) : (
            state.wsEvents.map((event, i) => (
              <div key={i} className="event-stream-item">
                <span className="event-time">{new Date(event.timestamp).toLocaleTimeString()}</span>
                <span className="event-type-tag">{eventName(event)}</span>
                {event.data && (
                  <details className="event-data-details">
                    <summary>详情</summary>
                    <pre className="event-data-preview">
                      {typeof event.data === 'string' ? event.data : JSON.stringify(event.data, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
