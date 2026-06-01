import { useMemo, useState } from 'react'
import type { AgentInfo, CatalogListItem } from '../types'
import './CatalogList.css'

const KIND_LABEL: Record<CatalogListItem['kind'], string> = {
  tool: '工具',
  skill: 'Skill',
  mcp: 'MCP',
}

interface CatalogListProps {
  items: CatalogListItem[]
  agents: AgentInfo[]
  onAssemble: (
    name: string,
    agentName: string,
    env?: Record<string, string>
  ) => void | Promise<void>
  loading?: boolean
  error?: string
  /** 正在装配中的 catalog 项名称（用于禁用按钮 + loading 文案）。 */
  assemblingName?: string | null
  /** 自定义空态文案。 */
  emptyHint?: string
}

interface RowProps {
  item: CatalogListItem
  agents: AgentInfo[]
  onAssemble: CatalogListProps['onAssemble']
  assembling: boolean
}

// 从 MCP detail.args / command 中嗅探 <PLACEHOLDER> 占位符以及 env key，
// 给用户提供「装配前可填」的占位输入。
function collectMcpEnvKeys(item: CatalogListItem): string[] {
  const detail = item.detail || {}
  const env = (detail.env || {}) as Record<string, unknown>
  return Object.keys(env)
}

function CatalogRow({ item, agents, onAssemble, assembling }: RowProps) {
  const [agentName, setAgentName] = useState(agents[0]?.name || '')
  const [expanded, setExpanded] = useState(false)
  const [envDraft, setEnvDraft] = useState<Record<string, string>>({})

  const envKeys = useMemo(
    () => (item.kind === 'mcp' ? collectMcpEnvKeys(item) : []),
    [item]
  )

  // agents 异步到达后，select 默认值兜底。
  const effectiveAgent = agentName || agents[0]?.name || ''

  const handleAssemble = () => {
    if (!effectiveAgent) return
    const env =
      item.kind === 'mcp' && Object.keys(envDraft).length > 0
        ? envDraft
        : undefined
    void onAssemble(item.name, effectiveAgent, env)
  }

  const usedBy = item.used_by || []
  const canShowDetail =
    item.kind === 'tool'
      ? Boolean(item.detail?.parameters)
      : item.kind === 'mcp'
      ? envKeys.length > 0 || Boolean(item.detail?.command)
      : Boolean(item.detail?.instructions_preview)

  return (
    <div className="catalog-row">
      <div className="catalog-row__main">
        <div className="catalog-row__head">
          <strong className="catalog-row__name">{item.name}</strong>
          <span className={`pill catalog-row__kind catalog-row__kind--${item.kind}`}>
            {KIND_LABEL[item.kind]}
          </span>
          {canShowDetail && (
            <button
              type="button"
              className="btn-xs catalog-row__toggle"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? '收起' : '详情'}
            </button>
          )}
        </div>
        {item.description && (
          <div className="catalog-row__desc">{item.description}</div>
        )}
        <div className="catalog-row__usedby">
          <span className="catalog-row__usedby-label">已装配</span>
          {usedBy.length === 0 ? (
            <span className="text-muted catalog-row__usedby-empty">未装配</span>
          ) : (
            usedBy.map((agent) => (
              <span key={agent} className="pill pill--info catalog-row__chip">
                {agent}
              </span>
            ))
          )}
        </div>

        {expanded && item.kind === 'tool' && item.detail?.parameters && (
          <pre className="catalog-row__detail text-mono">
            {JSON.stringify(item.detail.parameters, null, 2)}
          </pre>
        )}
        {expanded && item.kind === 'skill' && item.detail?.instructions_preview && (
          <div className="catalog-row__detail catalog-row__detail--text">
            {item.detail.instructions_preview}
          </div>
        )}
        {expanded && item.kind === 'mcp' && (
          <div className="catalog-row__mcp">
            <div className="catalog-row__mcp-cmd text-mono">
              {item.detail?.command || ''}
              {Array.isArray(item.detail?.args) && item.detail.args.length > 0
                ? ` ${item.detail.args.join(' ')}`
                : ''}
            </div>
            {envKeys.length > 0 && (
              <div className="catalog-row__env">
                {envKeys.map((key) => (
                  <label key={key} className="catalog-row__env-field">
                    <span className="text-mono">{key}</span>
                    <input
                      type="text"
                      placeholder="装配后可填写，留空则用模板占位"
                      value={envDraft[key] || ''}
                      onChange={(event) =>
                        setEnvDraft((prev) => ({
                          ...prev,
                          [key]: event.target.value,
                        }))
                      }
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="catalog-row__assemble">
        <select
          aria-label={`装配 ${item.name} 的目标智能体`}
          value={effectiveAgent}
          onChange={(event) => setAgentName(event.target.value)}
          disabled={agents.length === 0 || assembling}
        >
          {agents.length === 0 ? (
            <option value="">无可用智能体</option>
          ) : (
            agents.map((agent) => (
              <option key={agent.name} value={agent.name}>
                {agent.name}
              </option>
            ))
          )}
        </select>
        <button
          type="button"
          className="btn-primary catalog-row__assemble-btn"
          onClick={handleAssemble}
          disabled={!effectiveAgent || assembling}
        >
          {assembling ? '装配中...' : '装配'}
        </button>
      </div>
    </div>
  )
}

/**
 * 仓库级「能力库」统一列表。三类能力（tools/skills/mcp）共用同一交互模型：
 * 每行展示名称 / 描述 / kind 徽标 / used_by chips，并支持选目标 agent 一键装配。
 * MCP 行可展开填写 env 占位。加载 / 错误 / 空态统一处理。
 */
export function CatalogList({
  items,
  agents,
  onAssemble,
  loading,
  error,
  assemblingName,
  emptyHint,
}: CatalogListProps) {
  if (loading) {
    return (
      <div className="catalog-list catalog-list--state">
        <div className="empty-state" style={{ padding: 28 }}>
          <span>能力库加载中...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="catalog-list catalog-list--state">
        <div className="alert alert--error">
          <span style={{ flex: 1 }}>{error}</span>
        </div>
      </div>
    )
  }

  if (!items || items.length === 0) {
    return (
      <div className="catalog-list catalog-list--state">
        <div className="empty-state" style={{ padding: 28 }}>
          <strong>能力库为空</strong>
          <span>{emptyHint || '仓库中暂未预置该类能力。'}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="catalog-list">
      {items.map((item) => (
        <CatalogRow
          key={`${item.kind}:${item.name}`}
          item={item}
          agents={agents}
          onAssemble={onAssemble}
          assembling={assemblingName === item.name}
        />
      ))}
    </div>
  )
}
