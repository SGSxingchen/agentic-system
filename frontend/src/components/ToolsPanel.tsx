import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type {
  AgentInfo,
  CatalogApiItem,
  CatalogListItem,
  CatalogToolItem,
} from '../types'
import { CatalogList } from './CatalogList'
import './ToolsPanel.css'

function toListItem(raw: CatalogToolItem): CatalogListItem {
  return {
    name: raw.name,
    description: raw.description,
    kind: 'tool',
    used_by: raw.used_by || [],
    detail: { parameters: raw.parameters },
  }
}

export function ToolsPanel() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [items, setItems] = useState<CatalogListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [assemblingName, setAssemblingName] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const [catalogRes, agentsRes] = await Promise.all([
      api.listCatalog('tools'),
      api.listAgents(),
    ])
    setLoading(false)
    if (agentsRes.status === 'ok' && Array.isArray(agentsRes.data)) {
      setAgents(agentsRes.data)
    }
    if (catalogRes.status !== 'ok' || !Array.isArray(catalogRes.data)) {
      setError(catalogRes.message || '加载工具库失败。')
      setItems([])
      return
    }
    setItems(
      (catalogRes.data as CatalogApiItem[])
        .filter((entry): entry is CatalogToolItem => entry.kind === 'tool')
        .map(toListItem)
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleAssemble = useCallback(
    async (name: string, agentName: string) => {
      setAssemblingName(name)
      setError('')
      setNotice('')
      const res = await api.assembleCapability('tools', name, agentName)
      setAssemblingName(null)
      if (res.status !== 'ok') {
        setError(res.message || `装配工具 ${name} 失败。`)
        return
      }
      setNotice(`已把工具 ${name} 装配到 ${agentName}。`)
      await load()
    },
    [load]
  )

  const handleUnassemble = useCallback(
    async (name: string, agentName: string) => {
      setAssemblingName(name)
      setError('')
      setNotice('')
      const res = await api.unassembleCapability('tools', name, agentName)
      setAssemblingName(null)
      if (res.status !== 'ok') {
        setError(res.message || `从 ${agentName} 卸下工具 ${name} 失败。`)
        return
      }
      setNotice(`已从 ${agentName} 卸下工具 ${name}。`)
      await load()
    },
    [load]
  )

  const stats = useMemo(() => {
    const assembled = items.filter((item) => item.used_by.length > 0).length
    return { total: items.length, assembled }
  }, [items])

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">工具</h1>
          <div className="page__subtitle">
            仓库级工具能力库；选择目标智能体即可一键装配到其工具集。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" onClick={load} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
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
      {notice && (
        <div className="alert alert--success">
          <span style={{ flex: 1 }}>{notice}</span>
          <button className="btn-xs" onClick={() => setNotice('')}>
            关闭
          </button>
        </div>
      )}

      <div className="tools-stats">
        <div className="tools-stats__card">
          <div className="tools-stats__label">工具总数</div>
          <div className="tools-stats__value">{stats.total}</div>
        </div>
        <div className="tools-stats__card">
          <div className="tools-stats__label">已被装配</div>
          <div className="tools-stats__value">
            {stats.assembled} <span>/ {stats.total}</span>
          </div>
        </div>
      </div>

      <section className="console-card">
        <header className="console-card__header">
          <span className="console-card__title">能力库</span>
          <span className="text-muted">{items.length} 项</span>
        </header>
        <div className="console-card__body--flush">
          <CatalogList
            onUnassemble={handleUnassemble}
            items={items}
            agents={agents}
            onAssemble={handleAssemble}
            loading={loading}
            assemblingName={assemblingName}
            emptyHint="仓库中暂未注册任何工具能力。"
          />
        </div>
      </section>
    </div>
  )
}
