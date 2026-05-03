import { useState, useEffect, useCallback, useRef } from 'react'
import { useAppStore } from '../store/appStore'
import * as api from '../api/client'
import './MonitorPanel.css'

export function MonitorPanel() {
  const { state, dispatch } = useAppStore()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const eventListRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const fetchHealth = useCallback(async () => {
    const res = await api.getHealth()
    if (res.status === 'ok' && res.data) {
      dispatch({ type: 'SET_HEALTH', payload: res.data })
      setError(null)
    } else {
      setError(res.message || '无法连接到后端服务')
    }
    setLoading(false)
  }, [dispatch])

  useEffect(() => {
    fetchHealth()
    const timer = setInterval(fetchHealth, 5000)
    return () => clearInterval(timer)
  }, [fetchHealth])

  // 自动滚动到底部
  useEffect(() => {
    if (autoScroll && eventListRef.current) {
      eventListRef.current.scrollTop = eventListRef.current.scrollHeight
    }
  }, [state.wsEvents, autoScroll])

  const handleEventScroll = () => {
    if (eventListRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = eventListRef.current
      setAutoScroll(scrollHeight - scrollTop - clientHeight < 50)
    }
  }

  const health = state.health
  const isBackendDown = !health && !loading
  const latestProgress = [...state.wsEvents]
    .reverse()
    .find((event) => (event.event_type || event.type) === 'agent_progress')

  const healthDotColor = (ok: boolean | undefined) => {
    if (isBackendDown) return '#9CA3AF'
    return ok ? '#16A34A' : '#DC2626'
  }

  return (
    <div className="monitor-panel">
      <div className="panel-header">
        <h2>系统监控</h2>
        <button className="refresh-btn" onClick={fetchHealth}>
          刷新
        </button>
      </div>

      {error && <div className="monitor-error">{error}</div>}

      {/* Health Status Cards */}
      <div className="health-cards">
        <div
          className={`health-card ${
            health ? 'healthy' : 'unhealthy'
          }`}
        >
          <div
            className="health-card-icon"
            style={{
              backgroundColor: healthDotColor(!!health),
            }}
          />
          <div className="health-card-info">
            <div className="health-card-label">系统状态</div>
            <div className="health-card-value">
              {loading ? '检查中...' : health ? '运行中' : '离线'}
            </div>
          </div>
        </div>

        <div
          className={`health-card ${
            health?.bus_running ? 'healthy' : 'unhealthy'
          }`}
        >
          <div
            className="health-card-icon"
            style={{ backgroundColor: healthDotColor(health?.bus_running) }}
          />
          <div className="health-card-info">
            <div className="health-card-label">事件总线</div>
            <div className="health-card-value">
              {isBackendDown ? '未知' : health?.bus_running ? '运行中' : '未运行'}
            </div>
          </div>
        </div>

        <div
          className={`health-card ${
            health?.agent_loaded ? 'healthy' : 'unhealthy'
          }`}
        >
          <div
            className="health-card-icon"
            style={{ backgroundColor: healthDotColor(health?.agent_loaded) }}
          />
          <div className="health-card-info">
            <div className="health-card-label">Agent 引擎</div>
            <div className="health-card-value">
              {isBackendDown ? '未知' : health?.agent_loaded ? '已加载' : '未加载'}
            </div>
          </div>
        </div>

        <div
          className={`health-card ${
            health?.memory_initialized ? 'healthy' : 'unhealthy'
          }`}
        >
          <div
            className="health-card-icon"
            style={{ backgroundColor: healthDotColor(health?.memory_initialized) }}
          />
          <div className="health-card-info">
            <div className="health-card-label">记忆系统</div>
            <div className="health-card-value">
              {isBackendDown ? '未知' : health?.memory_initialized ? '已初始化' : '未初始化'}
            </div>
          </div>
        </div>
      </div>

      {/* Connection Info */}
      <div className="monitor-section">
        <h3>连接信息</h3>
        <div className="info-grid">
          <div className="info-item">
            <span className="info-label">WebSocket</span>
            <span
              className={`info-value ${
                state.connected ? 'text-success' : 'text-danger'
              }`}
            >
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
          {health?.version && (
            <div className="info-item">
              <span className="info-label">版本</span>
              <span className="info-value">{health.version}</span>
            </div>
          )}
          {health?.uptime != null && (
            <div className="info-item">
              <span className="info-label">运行时间</span>
              <span className="info-value">
                {health.uptime > 3600
                  ? `${Math.floor(health.uptime / 3600)}h ${Math.floor((health.uptime % 3600) / 60)}m`
                  : health.uptime > 60
                  ? `${Math.floor(health.uptime / 60)}m ${health.uptime % 60}s`
                  : `${health.uptime}s`}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="monitor-section">
        <h3>Agent 当前进度</h3>
        {latestProgress?.data ? (
          <div className="progress-snapshot">
            <div>
              <span className="info-label">Activity</span>
              <strong>{latestProgress.data.activity || latestProgress.data.current_step || 'running'}</strong>
            </div>
            <div>
              <span className="info-label">Status</span>
              <strong>{latestProgress.data.status || '-'}</strong>
            </div>
            {(latestProgress.data.tool || latestProgress.data.agent) && (
              <div>
                <span className="info-label">Target</span>
                <strong>{latestProgress.data.tool || latestProgress.data.agent}</strong>
              </div>
            )}
            {latestProgress.data.task_id && (
              <div>
                <span className="info-label">Task</span>
                <strong>{latestProgress.data.task_id}</strong>
              </div>
            )}
          </div>
        ) : (
          <div className="event-stream-empty event-stream-empty--compact">
            等待 Agent 进度事件...
          </div>
        )}
      </div>

      {/* Event Stream */}
      <div className="monitor-section event-stream-section">
        <div className="section-header">
          <h3>实时事件流</h3>
          <div className="event-stream-actions">
            <span className="event-count">
              {state.wsEvents.length} 条事件
            </span>
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
                {'\u2193'} 滚动到底部
              </button>
            )}
            <button
              className="clear-events-btn"
              onClick={() => dispatch({ type: 'CLEAR_WS_EVENTS' })}
            >
              清空
            </button>
          </div>
        </div>

        <div
          className="event-stream"
          ref={eventListRef}
          onScroll={handleEventScroll}
        >
          {state.wsEvents.length === 0 ? (
            <div className="event-stream-empty">
              <p>
                {state.connected
                  ? '等待系统事件...'
                  : '未连接 WebSocket，请确保后端服务已启动'}
              </p>
            </div>
          ) : (
            state.wsEvents.map((event, i) => (
              <div key={i} className="event-stream-item">
                <span className="event-time">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                <span className="event-type-tag">
                  {event.event_type || event.type}
                </span>
                {event.data && (
                  <details className="event-data-details">
                    <summary>详情</summary>
                    <pre className="event-data-preview">
                      {typeof event.data === 'string'
                        ? event.data
                        : JSON.stringify(event.data, null, 2)}
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
