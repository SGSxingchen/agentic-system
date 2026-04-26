import { useState, useEffect, useCallback } from 'react'
import type { Task, TaskStatus } from '../types'
import './TaskPanel.css'

const API = ''

const STATUS_STYLES: Record<TaskStatus, { bg: string; color: string; label: string }> = {
  pending: { bg: '#F3F4F6', color: '#4B5563', label: '等待中' },
  planning: { bg: '#FEF3C7', color: '#92400E', label: '规划中' },
  coding: { bg: '#DBEAFE', color: '#1E40AF', label: '编码中' },
  reviewing: { bg: '#EDE9FE', color: '#5B21B6', label: '审查中' },
  running: { bg: '#DBEAFE', color: '#1E40AF', label: '运行中' },
  completed: { bg: '#DCFCE7', color: '#166534', label: '已完成' },
  failed: { bg: '#FEE2E2', color: '#991B1B', label: '失败' },
}

export function TaskPanel() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [newRequirement, setNewRequirement] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [apiAvailable, setApiAvailable] = useState(true)

  const fetchTasks = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(`${API}/api/tasks`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const body = await resp.json()
      const payload = body as Record<string, unknown>
      const taskList = Array.isArray(body)
        ? body
        : Array.isArray(payload.data)
          ? payload.data
          : Array.isArray(payload.tasks)
            ? payload.tasks
            : []
      setTasks(taskList as Task[])
      setApiAvailable(true)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '获取任务列表失败'
      setError(msg)
      setApiAvailable(false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTasks()
    const timer = setInterval(fetchTasks, 5000)
    return () => clearInterval(timer)
  }, [fetchTasks])

  const handleSubmit = async () => {
    if (!newRequirement.trim()) return
    setSubmitting(true)
    setError('')
    try {
      const resp = await fetch(`${API}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requirement: newRequirement.trim() }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setNewRequirement('')
      await fetchTasks()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '提交任务失败'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit()
    }
  }

  return (
    <div className="task-panel">
      <div className="panel-header">
        <h2>任务管理</h2>
        <button className="refresh-btn" onClick={fetchTasks}>
          刷新
        </button>
      </div>

      {/* 提交新任务 */}
      <div className="task-submit-area">
        <textarea
          className="task-input"
          placeholder="描述你的需求，例如：创建一个用户登录注册的 REST API..."
          value={newRequirement}
          onChange={(e) => setNewRequirement(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
        />
        <div className="task-submit-footer">
          <span className="task-hint">Ctrl+Enter 提交</span>
          <button
            className="task-submit-btn"
            onClick={handleSubmit}
            disabled={submitting || !newRequirement.trim()}
          >
            {submitting ? '提交中...' : '提交任务'}
          </button>
        </div>
      </div>

      {error && (
        <div className="task-error">
          {!apiAvailable ? '无法连接到后端服务 — ' : ''}{error}
        </div>
      )}

      {/* 任务列表 */}
      {loading && tasks.length === 0 ? (
        <div className="task-loading">
          <div className="loading-spinner" />
          <span>加载中...</span>
        </div>
      ) : tasks.length === 0 ? (
        <div className="task-empty">
          <div className="placeholder-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 11l3 3L22 4" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
            </svg>
          </div>
          <h3>暂无任务</h3>
          <p>
            {apiAvailable
              ? '在上方输入需求描述，提交你的第一个任务吧！'
              : '无法连接到后端服务。请确保后端已启动后刷新。'}
          </p>
        </div>
      ) : (
        <div className="task-list">
          {tasks.map((task) => {
            const taskId = task.id || task.task_id || ''
            const style = STATUS_STYLES[task.status] || STATUS_STYLES.pending
            return (
              <div
                key={taskId}
                className={`task-card ${expandedId === taskId ? 'expanded' : ''}`}
                onClick={() => {
                  setExpandedId(expandedId === taskId ? null : taskId)
                }}
              >
                <div className="task-card-header">
                  <div className="task-info">
                    <span className="task-id">#{taskId.slice(0, 8)}</span>
                    <span className="task-name">
                      {task.name || task.requirement || '未命名任务'}
                    </span>
                  </div>
                  <span
                    className="task-status-badge"
                    style={{ backgroundColor: style.bg, color: style.color }}
                  >
                    {style.label}
                  </span>
                </div>

                {task.requirement && (
                  <p className="task-requirement">{task.requirement}</p>
                )}

                <div className="task-meta">
                  <span>{new Date(task.created_at).toLocaleString('zh-CN')}</span>
                  {task.agent && <span>{task.agent}</span>}
                </div>

                {/* 展开详情 */}
                {expandedId === taskId && (
                  <div className="task-details">
                    {task.plan && (
                      <div className="detail-section">
                        <h4>规划</h4>
                        <pre>{JSON.stringify(task.plan, null, 2)}</pre>
                      </div>
                    )}
                    {task.code && (
                      <div className="detail-section">
                        <h4>代码</h4>
                        <pre>{typeof task.code === 'string' ? task.code : JSON.stringify(task.code, null, 2)}</pre>
                      </div>
                    )}
                    {task.review && (
                      <div className="detail-section">
                        <h4>审查结果</h4>
                        <pre>{JSON.stringify(task.review, null, 2)}</pre>
                      </div>
                    )}
                    {task.output && (
                      <div className="detail-section">
                        <h4>输出</h4>
                        <pre>{JSON.stringify(task.output, null, 2)}</pre>
                      </div>
                    )}
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
