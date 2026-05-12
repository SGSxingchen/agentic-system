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

const DEMO_PRESETS = [
  {
    id: 'flask_api',
    title: '小型 Flask API',
    badge: '最适合答辩',
    agent: 'assistant',
    sessionId: 'defense-demo',
    workspaceId: 'demo-flask-api',
    goal:
      '答辩演示任务：生成一个老师一看就懂的小型 Flask Todo API。要求输出 app.py 代码，包含 /health、/todos GET、/todos POST 三个接口；说明运行命令和两条 curl 示例；最后总结用了哪些步骤、工具或子 Agent。不要启动服务，只生成可复制的代码和说明。',
    why: '展示需求理解 → 代码生成 → 可运行说明，最直观。',
  },
  {
    id: 'python_function',
    title: 'Python 工具函数',
    badge: '快速稳定',
    agent: 'assistant',
    sessionId: 'defense-demo',
    workspaceId: 'demo-python-utils',
    goal:
      '答辩演示任务：编写一个 Python 工具函数 normalize_phone_numbers(text: str) -> list[str]，从中英文混合文本中提取并规范化手机号。要求给出函数代码、3 个示例输入输出、2 个 pytest 测试用例，并解释边界条件。',
    why: '输出短、成功率高，便于现场讲解正确性和测试。',
  },
  {
    id: 'data_script',
    title: 'CSV 数据处理脚本',
    badge: '体现工具链',
    agent: 'assistant',
    sessionId: 'defense-demo',
    workspaceId: 'demo-data-cleaning',
    goal:
      '答辩演示任务：生成一个 Python CSV 数据清洗脚本 clean_sales.py。输入 sales.csv，清理空金额、统一日期格式、按商品汇总销售额，输出 summary.csv。要求给出核心代码、示例 CSV、运行命令和结果说明。',
    why: '展示脚本生成、数据处理流程和可观测输出。',
  },
] as const

function shortId(value?: string | null) {
  return value ? value.slice(0, 8) : '--------'
}

function statusStyle(status: TaskStatus) {
  return STATUS_STYLES[status] || STATUS_STYLES.pending
}

function formatDateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN')
}

function formatDuration(ms?: number | null) {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}

function stringifyValue(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function previewValue(value: unknown, max = 180): string {
  const text = stringifyValue(value).replace(/\s+/g, ' ').trim()
  if (!text) return ''
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function eventTitle(type: string) {
  const labels: Record<string, string> = {
    created: 'Run 已创建',
    started: 'Agent 开始执行',
    thinking: '流式生成片段',
    tool_call: '调用工具',
    tool_result: '工具返回',
    done: 'Agent 完成输出',
    error: '运行错误',
    killed: '运行已取消',
    step_started: '管线步骤开始',
    step_completed: '管线步骤完成',
    step_failed: '管线步骤失败',
  }
  return labels[type] || type
}

function eventTone(type: string) {
  if (type === 'error' || type === 'step_failed') return 'error'
  if (type === 'done' || type === 'step_completed') return 'success'
  if (type === 'tool_call' || type === 'tool_result') return 'tool'
  if (type === 'thinking') return 'thinking'
  return 'neutral'
}

function eventSummary(event: RunEvent) {
  const payload = event.payload || {}
  if (event.type === 'created') {
    return `目标已入队${payload.agent_name ? ` · Agent ${payload.agent_name}` : ''}`
  }
  if (event.type === 'started') {
    return `工作区 ${payload.workspace_root || payload.workspace_id || 'auto'}`
  }
  if (event.type === 'thinking') return previewValue(payload.content || payload, 220) || '模型正在流式生成内容'
  if (event.type === 'tool_call') return `${payload.tool || 'tool'} ${previewValue(payload.args, 140)}`
  if (event.type === 'tool_result') return `${payload.tool || 'tool'} → ${previewValue(payload.result, 180)}`
  if (event.type === 'done') return previewValue(payload.content || payload.output || payload, 220) || '最终输出已生成'
  if (event.type === 'error') return String(payload.error || payload.message || '运行失败')
  if (event.type === 'killed') return '用户请求取消，后台任务已终止'
  return previewValue(payload, 180)
}

function getEventDuration(event: RunEvent) {
  const payload = event.payload || {}
  if (typeof payload.elapsed_ms === 'number') return payload.elapsed_ms
  if (typeof payload.duration_ms === 'number') return payload.duration_ms
  return null
}

function getFinalOutput(run: Task, events: RunEvent[]) {
  if (run.output != null) return run.output
  const done = [...events].reverse().find((event) => event.type === 'done')
  if (!done) return null
  const payload = done.payload || {}
  return payload.content ?? payload.output ?? payload
}

function compactTimelineEvents(events: RunEvent[]): RunEvent[] {
  const compacted: RunEvent[] = []
  for (const event of events) {
    const previous = compacted[compacted.length - 1]
    if (event.type === 'thinking' && previous?.type === 'thinking') {
      previous.payload = {
        ...previous.payload,
        content: `${previous.payload?.content || ''}${event.payload?.content || ''}`,
        chunks: Number(previous.payload?.chunks || 1) + 1,
        last_ts: event.ts,
      }
    } else {
      compacted.push({
        ...event,
        payload: { ...(event.payload || {}) },
      })
    }
  }
  return compacted
}

function runElapsedMs(run: Task, events: RunEvent[]) {
  const done = [...events].reverse().find((event) => event.type === 'done' || event.type === 'error' || event.type === 'killed')
  const explicit = done ? getEventDuration(done) : null
  if (explicit != null) return explicit
  const start = new Date(run.created_at).getTime()
  const endSource = run.ended_at || run.updated_at || done?.ts
  const end = endSource ? new Date(endSource).getTime() : Date.now()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null
  return end - start
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
  const [demoSubmittingId, setDemoSubmittingId] = useState<string | null>(null)
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

  const submitRun = async (params: {
    goal: string
    agentName?: string
    sessionId?: string
    workspaceId?: string
    demoId?: string
  }) => {
    if (!params.goal.trim()) return
    setSubmitting(true)
    if (params.demoId) setDemoSubmittingId(params.demoId)
    setError('')
    const res = await api.createRun({
      goal: params.goal.trim(),
      agent_name: params.agentName || agentName || 'assistant',
      session_id: params.sessionId?.trim() || sessionId.trim() || undefined,
      workspace_id: params.workspaceId?.trim() || workspaceId.trim() || undefined,
      mode: 'autonomous',
      strategy: 'agent_decides',
    })
    if (res.status === 'ok') {
      if (!params.demoId) setGoal('')
      if (res.data?.id) setExpandedId(res.data.id)
      await fetchRuns()
    } else {
      setError(res.message || '创建运行失败')
    }
    setSubmitting(false)
    setDemoSubmittingId(null)
  }

  const handleSubmit = async () => {
    await submitRun({ goal })
  }

  const applyDemoPreset = (preset: typeof DEMO_PRESETS[number]) => {
    setAgentName(preset.agent)
    setSessionId(preset.sessionId)
    setWorkspaceId(preset.workspaceId)
    setGoal(preset.goal)
  }

  const submitDemoPreset = async (preset: typeof DEMO_PRESETS[number]) => {
    applyDemoPreset(preset)
    await submitRun({
      goal: preset.goal,
      agentName: preset.agent,
      sessionId: preset.sessionId,
      workspaceId: preset.workspaceId,
      demoId: preset.id,
    })
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
          <h2>Agent Run 答辩演示台</h2>
          <p className="panel-subtitle">用一个清晰任务现场展示：主 Agent 理解需求，按需调用工具/子 Agent，事件 transcript 全程落盘，可观测、可追踪、可复盘。</p>
        </div>
        <button className="refresh-btn" onClick={fetchRuns}>刷新</button>
      </div>

      <section className="demo-launchpad" aria-label="答辩 Demo 预设任务">
        <div className="demo-launchpad__intro">
          <span className="demo-kicker">Defense Demo</span>
          <h3>一键预设任务</h3>
          <p>老师现场只需点一个任务，就能看到 Run 创建、Agent 执行、流式生成、工具调用、最终输出和 transcript 时间线。</p>
        </div>
        <div className="demo-preset-grid">
          {DEMO_PRESETS.map((preset) => (
            <article className="demo-preset-card" key={preset.id}>
              <div className="demo-preset-card__top">
                <span>{preset.badge}</span>
                <strong>{preset.title}</strong>
              </div>
              <p>{preset.why}</p>
              <div className="demo-preset-card__meta">
                <span>Agent: {preset.agent}</span>
                <span>Workspace: {preset.workspaceId}</span>
              </div>
              <div className="demo-preset-card__actions">
                <button type="button" className="btn-secondary-sm" onClick={() => applyDemoPreset(preset)}>
                  填入表单
                </button>
                <button
                  type="button"
                  className="btn-primary-sm"
                  onClick={() => submitDemoPreset(preset)}
                  disabled={submitting}
                >
                  {demoSubmittingId === preset.id ? '提交中…' : '一键演示'}
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

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
          <h3>还没有演示 Run</h3>
          <p>{apiAvailable ? '从上方选择一个答辩预设，现场展示多智能体协作、长期记忆注入、工具调用和可观测 transcript。' : '无法连接到后端服务。请确保后端已启动后刷新。'}</p>
          <div className="task-empty-points">
            <span>多智能体：assistant 可委派 planner/coder/reviewer</span>
            <span>记忆：相关长期资料会作为不可信上下文注入</span>
            <span>可观测：created / stream / tool / done 全部进入时间线</span>
          </div>
        </div>
      ) : (
        <div className="task-list run-list">
          {runs.map((run) => {
            const runId = run.id || run.task_id || ''
            const style = statusStyle(run.status)
            const events = eventsByRun[runId] || []
            const timelineEvents = compactTimelineEvents(events).slice(-80)
            const finalOutput = getFinalOutput(run, events)
            const elapsed = runElapsedMs(run, events)
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
                  <span>Run ID: {runId}</span>
                  <span>Agent: {run.agent_name || run.agent || 'unknown'}</span>
                  <span>Status: {run.status}</span>
                  <span>Workspace: {run.workspace_id || 'auto'}</span>
                  <span>耗时: {formatDuration(elapsed)}</span>
                  {run.session_id && <span>Session: {run.session_id}</span>}
                  <span>Strategy: {run.strategy || 'agent_decides'}</span>
                </div>
                {formatProgress(run) && <p className="task-progress run-progress">{formatProgress(run)}</p>}
                <div className="task-meta">
                  <span>创建: {formatDateTime(run.created_at)}</span>
                  {run.ended_at && <span>结束: {formatDateTime(run.ended_at)}</span>}
                  {run.output_file && <span>Transcript: {run.output_file}</span>}
                </div>

                {expandedId === runId && (
                  <div className="task-details run-details">
                    <div className="run-snapshot-grid">
                      <div><span>run_id</span><strong>{runId}</strong></div>
                      <div><span>agent</span><strong>{run.agent_name || run.agent || 'unknown'}</strong></div>
                      <div><span>status</span><strong>{run.status}</strong></div>
                      <div><span>workspace</span><strong>{run.workspace_id || 'auto'}</strong></div>
                      <div><span>created</span><strong>{formatDateTime(run.created_at)}</strong></div>
                      <div><span>elapsed</span><strong>{formatDuration(elapsed)}</strong></div>
                    </div>

                    <div className="detail-section">
                      <div className="run-section-heading">
                        <h4>Transcript 时间线</h4>
                        <span>{events.length} raw events · {timelineEvents.length} timeline items</span>
                      </div>
                      {events.length === 0 ? <p className="run-muted">暂无事件或正在加载 transcript。</p> : (
                        <div className="run-timeline">
                          {timelineEvents.map((event, idx) => {
                            const duration = getEventDuration(event)
                            return (
                              <div className={`run-timeline-item tone-${eventTone(event.type)}`} key={`${event.ts}-${idx}`}>
                                <div className="run-timeline-dot" />
                                <div className="run-timeline-card">
                                  <div className="run-timeline-card__head">
                                    <strong>{eventTitle(event.type)}</strong>
                                    <span>{formatTime(event.ts)}</span>
                                  </div>
                                  <p>{eventSummary(event)}</p>
                                  <div className="run-timeline-card__meta">
                                    <span>{event.type}</span>
                                    {event.payload?.tool && <span>tool: {String(event.payload.tool)}</span>}
                                    {event.payload?.chunks && <span>{String(event.payload.chunks)} chunks</span>}
                                    {duration != null && <span>{formatDuration(duration)}</span>}
                                  </div>
                                  <details>
                                    <summary>查看原始事件</summary>
                                    <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                                  </details>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>

                    {finalOutput != null && (
                      <details className="run-final-output" open={run.status === 'completed'}>
                        <summary>
                          <span>最终输出</span>
                          <small>完成后可展开，用于答辩讲解结果与验收</small>
                        </summary>
                        <pre>{stringifyValue(finalOutput)}</pre>
                      </details>
                    )}
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
