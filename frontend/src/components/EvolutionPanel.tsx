import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { EvolutionSystemComponent, EvolutionSystemStatus } from '../types'
import './EvolutionPanel.css'

const COMPONENT_ORDER = [
  'agents',
  'tools',
  'skills',
  'memory',
  'models',
  'runtime',
  'evolution_loop',
  'observability',
]

function statusLabel(status?: string): string {
  switch (status) {
    case 'healthy':
    case 'ready':
      return '就绪'
    case 'warning':
    case 'attention_needed':
      return '需关注'
    case 'empty':
      return '暂无数据'
    case 'disabled':
      return '已停用'
    default:
      return status || '未知'
  }
}

function metricValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '启用' : '关闭'
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (Array.isArray(value)) return String(value.length)
  if (typeof value === 'object') return String(Object.keys(value as Record<string, unknown>).length)
  return String(value)
}

function formatItemValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]'
    return value
      .map((item) => {
        if (typeof item === 'string') return item
        if (typeof item === 'object' && item && 'name' in item) {
          return `${(item as { name?: string }).name}: ${(item as { exists?: boolean }).exists ? '正常' : '缺失'}`
        }
        return JSON.stringify(item)
      })
      .join(' / ')
  }
  return JSON.stringify(value)
}

function componentById(status: EvolutionSystemStatus | null, id: string) {
  return status?.components.find((component) => component.id === id) || null
}

function ComponentCard({ component }: { component: EvolutionSystemComponent }) {
  const metrics = Object.entries(component.metrics || {}).slice(0, 4)
  const items = component.items || []

  return (
    <section className={`system-card status-${component.status || 'unknown'}`}>
      <div className="system-card__header">
        <div>
          <span className="system-card__eyebrow">{component.id.replace(/_/g, ' / ')}</span>
          <h3>{component.title}</h3>
        </div>
        <span className="state-pill">{statusLabel(component.status)}</span>
      </div>

      <p className="system-card__summary">{component.summary || component.empty_state || '暂无运行状态说明。'}</p>

      <div className="metric-strip">
        {metrics.length === 0 ? (
          <span className="metric-empty">暂无指标</span>
        ) : metrics.map(([key, value]) => (
          <div key={key} className="mini-metric">
            <span>{key.replace(/_/g, ' ')}</span>
            <strong>{metricValue(value)}</strong>
          </div>
        ))}
      </div>

      <div className="component-items">
        {items.length === 0 ? (
          <div className="empty-line">{component.empty_state || '该组件暂无可展示条目。'}</div>
        ) : items.slice(0, 6).map((item, index) => {
          const record = item as Record<string, unknown>
          const name = record.name || record.agent || record.label || `item_${index + 1}`
          const description = record.description || record.value || record.status || record.type || ''
          return (
            <div className="component-item" key={`${component.id}-${String(name)}-${index}`}>
              <div>
                <strong>{String(name)}</strong>
                <span>{formatItemValue(description)}</span>
              </div>
              {'capability_count' in record && <em>{metricValue(record.capability_count)} 项能力</em>}
              {'loaded_count' in record && <em>{metricValue(record.loaded_count)} 项已加载</em>}
              {'mode' in record && record.mode ? <em>{String(record.mode)}</em> : null}
            </div>
          )
        })}
      </div>
    </section>
  )
}

export function EvolutionPanel() {
  const [status, setStatus] = useState<EvolutionSystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloading, setReloading] = useState(false)
  const [goal, setGoal] = useState('请基于当前架构状态提出一次最小可行的系统级改造。')
  const [command, setCommand] = useState('')
  const [commandTargets, setCommandTargets] = useState<string[]>([])
  const [generating, setGenerating] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [taskMessage, setTaskMessage] = useState('')

  const fetchStatus = useCallback(async () => {
    setLoading(true)
    const res = await api.getEvolutionSystemStatus()
    if (res.status === 'ok' && res.data) {
      setStatus(res.data)
      setError('')
    } else {
      setError(res.message || '无法加载系统架构状态')
    }
    setLoading(false)
  }, [])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const orderedComponents = useMemo(() => {
    const byId = new Map((status?.components || []).map((component) => [component.id, component]))
    const ordered = COMPONENT_ORDER.map((id) => byId.get(id)).filter(Boolean) as EvolutionSystemComponent[]
    const leftovers = (status?.components || []).filter((component) => !COMPONENT_ORDER.includes(component.id))
    return [...ordered, ...leftovers]
  }, [status])

  const graphEdges = status?.graph.edges || []
  const agents = componentById(status, 'agents')
  const tools = componentById(status, 'tools')
  const memory = componentById(status, 'memory')
  const runtime = componentById(status, 'runtime')

  const handleReload = async () => {
    setReloading(true)
    const res = await api.reloadEvolutionExtensions()
    if (res.status !== 'ok') setError(res.message || '动态扩展重新加载失败')
    await fetchStatus()
    setReloading(false)
  }

  const handleGenerateCommand = async () => {
    if (!goal.trim()) {
      setError('请先描述系统改造目标')
      return
    }
    setGenerating(true)
    setTaskMessage('')
    const res = await api.createEvolutionCommand(goal.trim())
    setGenerating(false)
    if (res.status === 'ok' && res.data) {
      setCommand(res.data.command)
      setCommandTargets(res.data.target_components || [])
      setError('')
    } else {
      setError(res.message || '生成进化指令失败')
    }
  }

  const handleSubmitCommand = async () => {
    if (!command.trim()) return
    setSubmitting(true)
    const res = await api.submitTask(command.trim())
    setSubmitting(false)
    if (res.status === 'ok' && res.data) {
      setTaskMessage(`已提交为系统改造任务：${res.data.task_id || res.data.id || 'pending'}`)
    } else {
      setError(res.message || '提交进化任务失败')
    }
  }

  return (
    <div className="evolution-panel">
      <header className="evolution-hero">
        <div className="hero-copy">
          <p className="evolution-kicker">系统进化</p>
          <h2>系统架构状态与进化指令</h2>
          <p>本页用于查看 Agent、工具、记忆、模型、运行时与观测配置的真实状态，并基于当前快照生成可执行的系统级改造任务。</p>
        </div>
        <button className="refresh-btn" onClick={handleReload} disabled={reloading}>
          {reloading ? '重新加载中...' : '重新加载扩展'}
        </button>
      </header>

      {error && <div className="evolution-error">{error}</div>}

      <section className="command-center">
        <div>
          <p className="evolution-kicker">进化指令</p>
          <h3>生成系统级改造指令</h3>
          <p>输入目标后，系统会将当前架构快照写入任务指令，要求执行者先审查架构状态，再设计最小改造、实施并验证。</p>
        </div>
        <div className="command-box">
          <textarea value={goal} onChange={(event) => setGoal(event.target.value)} rows={3} placeholder="例如：增强长期记忆召回解释、改进失败恢复、整理观测面板信息密度。" />
          <div className="command-actions">
            <button className="btn-primary-sm" onClick={handleGenerateCommand} disabled={generating}>
              {generating ? '生成中...' : '生成进化指令'}
            </button>
            <button className="btn-secondary-sm" onClick={handleSubmitCommand} disabled={!command || submitting}>
              {submitting ? '提交中...' : '提交为任务'}
            </button>
          </div>
        </div>
        {command && (
          <div className="command-output">
            <div className="command-output__top">
              <strong>已生成指令</strong>
              <span>{commandTargets.length ? `聚焦：${commandTargets.join(' / ')}` : '系统级'}</span>
            </div>
            <pre>{command}</pre>
            {taskMessage && <div className="task-message">{taskMessage}</div>}
          </div>
        )}
      </section>

      <div className="evolution-stats">
        <div className="evolution-stat-card"><span>就绪状态</span><strong>{loading ? '加载中' : statusLabel(status?.overview.readiness)}</strong></div>
        <div className="evolution-stat-card"><span>智能体</span><strong>{agents?.metrics.total ?? status?.overview.agent_count ?? 0}</strong></div>
        <div className="evolution-stat-card"><span>工具能力</span><strong>{tools?.metrics.total ?? status?.overview.tool_count ?? 0}</strong></div>
        <div className="evolution-stat-card"><span>长期记忆</span><strong>{memory?.metrics.total ?? 0}</strong></div>
        <div className="evolution-stat-card"><span>运行实例</span><strong>{runtime?.metrics.tasks ?? status?.overview.run_count ?? 0}</strong></div>
      </div>

      <section className="architecture-map">
        <div className="map-spine">
          <span>当前架构</span>
          <strong>{status?.overview.system_name || 'Agentic System'}</strong>
          <em>{status?.overview.model || '模型状态不可用'}</em>
        </div>
        <div className="map-lanes">
          {loading ? (
            <div className="evolution-placeholder">正在加载系统架构状态...</div>
          ) : graphEdges.length === 0 ? (
            <div className="evolution-placeholder">暂无智能体/工具调用关系；请检查智能体能力配置。</div>
          ) : graphEdges.slice(0, 18).map((edge) => (
            <div key={`${edge.source}-${edge.target}`} className="edge-item">
              <span className={`edge-kind ${edge.kind}`}>{edge.kind}</span>
              <strong>{edge.source}</strong>
              <span className="edge-arrow">→</span>
              <strong>{edge.target}</strong>
            </div>
          ))}
        </div>
      </section>

      <div className="system-grid">
        {orderedComponents.map((component) => <ComponentCard key={component.id} component={component} />)}
      </div>
    </div>
  )
}
