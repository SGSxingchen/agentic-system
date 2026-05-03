import { useState, useEffect, useCallback } from 'react'
import type { AgentInfo, RunEvent, Task, TaskStatus } from '../types'
import * as api from '../api/client'
import './TaskPanel.css'

const STATUS_STYLES: Record<TaskStatus, { bg: string; color: string; label: string }> = {
  pending: { bg: '#F3F4F6', color: '#4B5563', label: '等待中' },
  planning: { bg: '#FEF3C7', color: '#92400E', label: '规划中' },
  coding: { bg: '#DBEAFE', color: '#1E40AF', label: '编码中' },
  reviewing: { bg: '#EDE9FE', color: '#5B21B6', label: '审查中' },
  running: { bg: '#DBEAFE', color: '#1E40AF', label: '运行中' },
  completed: { bg: '#DCFCE7', color: '#166534', label: '已完成' },
  failed: { bg: '#FEE2E2', color: '#991B1B', label: '失败' },
  killed: { bg: '#F3F4F6', color: '#374151', label: '已终止' },
}

const ACTIVE = new Set<TaskStatus>(['pending', 'running', 'planning', 'coding', 'reviewing'])

function shortId(value?: string | null) {
  return value ? value.slice(0, 8) : '--------'
}

function statusStyle(status: TaskStatus) {
  return STATUS_STYLES[status] || STATUS_STYLES.pending
}

export function TaskPanel() {
  const [runs, setRuns] = useState<Task[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [eventsByRun, setEventsByRun] = useState<Record<string, RunEvent[]>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [goal, setGoal] = useState('')
  const [agentName, setAgentName] = useState('assistant')
  const [sessionId, setSessionId] = useState('')
  const [workspaceId, setWorkspaceId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [apiAvailable, setApiAvailable] = useState(true)

  const fetchRuns = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.getRuns()
      if (res.status !== 'ok') throw new Error(res.message || '获取运行列表失败')
      setRuns(res.data || [])
      setApiAvailable(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '获取运行列表失败')
      setApiAvailable(false)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchAgents = useCallback(async () => {
    const res = await api.listAgents()
    if (res.status === 'ok' && res.data) {
      setAgents(res.data)
      if (!res.data.some((a) => a.name === agentName) && res.data[0]?.name) {
        setAgentName(res.data[0].name)
      }
    }
  }, [agentName])

  const fetchEvents = useCallback(async (runId: string) => {
    const res = await api.getRunEvents(runId)
    if (res.status === 'ok' && res.data) {
      setEventsByRun((prev) => ({ ...prev, [runId]: res.data?.events || [] }))
    }
  }, [])

  useEffect(() => {
    fetchRuns()
    fetchAgents()
    const timer = setInterval(fetchRuns, 3000)
    return () => clearInterval(timer)
  }, [fetchRuns, fetchAgents])

  useEffect(() => {
    if (expandedId) fetchEvents(expandedId)
  }, [expandedId, fetchEvents, runs])

  const handleSubmit = async () => {
    if (!goal.trim()) return
    setSubmitting(true)
    setError('')
    const res = await api.createRun({
      goal: goal.trim(),
      agent_name: agentName || 'assistant',
      session_id: sessionId.trim() || undefined,
      workspace_id: workspaceId.trim() || undefined,
      mode: 'autonomous',
      strategy: 'agent_decides',
    })
    if (res.status === 'ok') {
      setGoal('')
      if (res.data?.id) setExpandedId(res.data.id)
      await fetchRuns()
    } else {
      setError(res.message || '创建运行失败')
    }
    setSubmitting(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  const handleCancel = async (runId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const res = await api.cancelRun(runId)
    if (res.status !== 'ok') setError(res.message || '取消运行失败')
    await fetchRuns()
  }

  const formatProgress = (run: Task): string => {
    const p = run.progress
    if (!p) return ''
    const segs: string[] = []
    if (p.activity) segs.push(p.activity)
    if (p.last_tool) segs.push(`工具: ${p.last_tool}`)
    if (p.tool_count) segs.push(`${p.tool_count} 次工具`)
    if (p.total_tokens) segs.push(`${p.total_tokens} tokens`)
    return segs.join(' · ')
  }

  return (
    <div className="task-panel run-workspace-panel">
      <div className="panel-header">
        <div>
          <h2>Agent Run 工作区</h2>
          <p className="panel-subtitle">多开 agent/session/workspace/task 实例；调度层只管理状态和控制，下一步由 Agent 自主决定。</p>
        </div>
        <button className="refresh-btn" onClick={fetchRuns}>刷新</button>
      </div>

      <div className="task-submit-area run-submit-area">
        <div className="run-submit-grid">
          <label>
            <span>Agent</span>
            <select value={agentName} onChange={(e) => setAgentName(e.target.value)}>
              {agents.length === 0 && <option value="assistant">assistant</option>}
              {agents.map((agent) => <option key={agent.name} value={agent.name}>{agent.name}</option>)}
            </select>
          </label>
          <label>
            <span>Session</span>
            <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} placeholder="可选，例如 chat-001" />
          </label>
          <label>
            <span>Workspace</span>
            <input value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)} placeholder="留空自动创建隔离工作区" />
          </label>
        </div>
        <textarea
          className="task-input"
          placeholder="描述本次 Agent Run 的目标。Agent 会根据上下文和工具反馈自主选择下一步，而不是被固定管线驱动。"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={4}
        />
        <div className="task-submit-footer">
          <span className="task-hint">Ctrl+Enter 创建运行 · 旧 /api/tasks?pipeline=auto 已迁移到同一模型</span>
          <button className="task-submit-btn" onClick={handleSubmit} disabled={submitting || !goal.trim()}>
            {submitting ? '创建中...' : '创建 Agent Run'}
          </button>
        </div>
      </div>

      {error && <div className="task-error">{!apiAvailable ? '无法连接到后端服务 — ' : ''}{error}</div>}

      {loading && runs.length === 0 ? (
        <div className="task-loading"><div className="loading-spinner" /><span>加载中...</span></div>
      ) : runs.length === 0 ? (
        <div className="task-empty">
          <div className="placeholder-icon">◎</div>
          <h3>暂无 Agent Run</h3>
          <p>{apiAvailable ? '创建一个运行实例，开始并发 agent 工作。' : '无法连接到后端服务。请确保后端已启动后刷新。'}</p>
        </div>
      ) : (
        <div className="task-list run-list">
          {runs.map((run) => {
            const runId = run.id || run.task_id || ''
            const style = statusStyle(run.status)
            const events = eventsByRun[runId] || []
            return (
              <div
                key={runId}
                className={`task-card run-card ${expandedId === runId ? 'expanded' : ''}`}
                onClick={() => setExpandedId(expandedId === runId ? null : runId)}
              >
                <div className="task-card-header">
                  <div className="task-info">
                    <span className="task-id">run #{shortId(runId)}</span>
                    <span className="task-name">{run.goal || run.requirement || '未命名目标'}</span>
                  </div>
                  <div className="task-card-actions">
                    <span className="task-status-badge" style={{ backgroundColor: style.bg, color: style.color }}>{style.label}</span>
                    {ACTIVE.has(run.status) && <button className="task-cancel-btn" onClick={(e) => handleCancel(runId, e)}>取消</button>}
                  </div>
                </div>

                <div className="run-chips">
                  <span>Agent: {run.agent_name || run.agent || 'unknown'}</span>
                  <span>Workspace: {run.workspace_id || 'auto'}</span>
                  {run.session_id && <span>Session: {run.session_id}</span>}
                  <span>Strategy: {run.strategy || 'agent_decides'}</span>
                </div>
                {formatProgress(run) && <p className="task-progress run-progress">{formatProgress(run)}</p>}
                <div className="task-meta">
                  <span>{new Date(run.created_at).toLocaleString('zh-CN')}</span>
                  {run.ended_at && <span>结束: {new Date(run.ended_at).toLocaleString('zh-CN')}</span>}
                  {run.output_file && <span>Transcript: {run.output_file}</span>}
                </div>

                {expandedId === runId && (
                  <div className="task-details run-details">
                    <div className="detail-section">
                      <h4>事件流</h4>
                      {events.length === 0 ? <p className="run-muted">暂无事件或正在加载。</p> : (
                        <div className="run-event-list">
                          {events.slice(-40).map((event, idx) => (
                            <div className="run-event" key={`${event.ts}-${idx}`}>
                              <span className="run-event-type">{event.type}</span>
                              <span className="run-event-time">{new Date(event.ts).toLocaleTimeString('zh-CN')}</span>
                              <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    {run.output && <div className="detail-section"><h4>最终结果</h4><pre>{JSON.stringify(run.output, null, 2)}</pre></div>}
                    {run.error && <div className="detail-section"><h4>错误</h4><pre>{run.error}</pre></div>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
