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
  'evolution_pipeline',
  'observability',
]

function statusLabel(status?: string): string {
  switch (status) {
    case 'healthy':
    case 'ready':
      return 'Ready'
    case 'warning':
    case 'attention_needed':
      return 'Needs attention'
    case 'empty':
      return 'No data yet'
    case 'disabled':
      return 'Disabled'
    default:
      return status || 'Unknown'
  }
}

function metricValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (Array.isArray(value)) return String(value.length)
  if (typeof value === 'object') return String(Object.keys(value as Record<string, unknown>).length)
  return String(value)
}

function formatItemValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]'
    return value
      .map((item) => {
        if (typeof item === 'string') return item
        if (typeof item === 'object' && item && 'name' in item) {
          return `${(item as { name?: string }).name}: ${(item as { exists?: boolean }).exists ? 'ok' : 'missing'}`
        }
        return JSON.stringify(item)
      })
      .join(' · ')
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

      <p className="system-card__summary">{component.summary || component.empty_state || '暂无运行状态描述。'}</p>

      <div className="metric-strip">
        {metrics.length === 0 ? (
          <span className="metric-empty">暂无指标</span>
        ) : (
          metrics.map(([key, value]) => (
            <div key={key} className="mini-metric">
              <span>{key.replace(/_/g, ' ')}</span>
              <strong>{metricValue(value)}</strong>
            </div>
          ))
        )}
      </div>

      <div className="component-items">
        {items.length === 0 ? (
          <div className="empty-line">{component.empty_state || '该组件暂无可展示条目。'}</div>
        ) : (
          items.slice(0, 6).map((item, index) => {
            const record = item as Record<string, unknown>
            const name = record.name || record.agent || record.label || `item_${index + 1}`
            const description = record.description || record.value || record.status || record.type || ''
            return (
              <div className="component-item" key={`${component.id}-${String(name)}-${index}`}>
                <div>
                  <strong>{String(name)}</strong>
                  <span>{formatItemValue(description)}</span>
                </div>
                {'capability_count' in record && <em>{metricValue(record.capability_count)} tools</em>}
                {'loaded_count' in record && <em>{metricValue(record.loaded_count)} loaded</em>}
                {'mode' in record && record.mode ? <em>{String(record.mode)}</em> : null}
              </div>
            )
          })
        )}
      </div>
    </section>
  )
}

export function EvolutionPanel() {
  const [status, setStatus] = useState<EvolutionSystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloading, setReloading] = useState(false)
  const [goal, setGoal] = useState('让进化页面成为系统架构仪表盘，并能指导下一次系统级改造')
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

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

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
    if (res.status !== 'ok') {
      setError(res.message || '重新装载动态扩展失败')
    }
    await fetchStatus()
    setReloading(false)
  }

  const handleGenerateCommand = async () => {
    if (!goal.trim()) {
      setError('请先描述希望系统如何进化')
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
      setTaskMessage(`已提交为系统进化任务：${res.data.task_id || res.data.id || 'pending'}`)
    } else {
      setError(res.message || '提交进化任务失败')
    }
  }

  return (
    <div className="evolution-panel">
      <div className="evolution-hero">
        <div className="hero-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="hero-copy">
          <p className="evolution-kicker">Agentic System Evolution</p>
          <h2>系统架构状态与进化命令中心</h2>
          <p>
            进化不是“多加一个 assistant tool”。这里先展示整个 Agentic System 的运行态：Agents、Tools、Skills、Memory、Models、Pipeline、Reflection 与 Observability，
            再用一条明确命令引导系统级改造。
          </p>
        </div>
        <button className="refresh-btn" onClick={handleReload} disabled={reloading}>
          {reloading ? '装载中...' : '重新装载扩展'}
        </button>
      </div>

      {error && <div className="evolution-error">{error}</div>}

      <section className="command-center">
        <div>
          <p className="evolution-kicker">Evolution Command</p>
          <h3>用一句目标生成系统级进化指令</h3>
          <p>
            输入希望系统如何变强，系统会把当前架构快照写入任务指令，要求智能体先做架构审查、再实施、最后验证。
          </p>
        </div>
        <div className="command-box">
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            rows={3}
            placeholder="例如：增强长期记忆召回解释、让管线支持失败恢复、改造观测面板..."
          />
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
        <div className="evolution-stat-card">
          <span>Readiness</span>
          <strong>{loading ? '...' : statusLabel(status?.overview.readiness)}</strong>
        </div>
        <div className="evolution-stat-card">
          <span>Agents</span>
          <strong>{agents?.metrics.total ?? status?.overview.agent_count ?? 0}</strong>
        </div>
        <div className="evolution-stat-card">
          <span>Tools</span>
          <strong>{tools?.metrics.total ?? status?.overview.tool_count ?? 0}</strong>
        </div>
        <div className="evolution-stat-card highlight">
          <span>Memory</span>
          <strong>{memory?.metrics.total ?? 0}</strong>
        </div>
        <div className="evolution-stat-card">
          <span>Pipelines</span>
          <strong>{runtime?.metrics.templates ?? status?.overview.pipeline_count ?? 0}</strong>
        </div>
      </div>

      <section className="architecture-map">
        <div className="map-spine">
          <span>Current Architecture</span>
          <strong>{status?.overview.system_name || 'Agentic System'}</strong>
          <em>{status?.overview.model || 'model status unavailable'}</em>
        </div>
        <div className="map-lanes">
          {loading ? (
            <div className="evolution-placeholder">加载系统架构状态...</div>
          ) : graphEdges.length === 0 ? (
            <div className="evolution-placeholder">暂无 Agent/Tool 调用边；请检查 Agent tools 配置。</div>
          ) : (
            graphEdges.slice(0, 18).map((edge) => (
              <div key={`${edge.source}-${edge.target}`} className="edge-item">
                <span className={`edge-kind ${edge.kind}`}>{edge.kind}</span>
                <strong>{edge.source}</strong>
                <span className="edge-arrow">→</span>
                <strong>{edge.target}</strong>
              </div>
            ))
          )}
        </div>
      </section>

      <div className="system-grid">
        {orderedComponents.map((component) => (
          <ComponentCard key={component.id} component={component} />
        ))}
      </div>
    </div>
  )
}
