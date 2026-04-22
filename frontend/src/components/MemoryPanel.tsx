import { useState, useEffect, useCallback } from 'react'
import * as api from '../api/client'
import './MemoryPanel.css'

interface MemoryItem {
  id: string
  content: string
  type: string
  importance: number
  access_count?: number
  created_at: string
  last_accessed?: string
  metadata?: Record<string, any>
}

interface MemoryStatsData {
  total_memories?: number
  total?: number
  by_type: Record<string, number>
  oldest_memory?: string
  newest_memory?: string
}

interface MemoryPanelProps {
  onClose: () => void
}

const MEMORY_TYPES = ['episodic', 'semantic', 'procedural']

const TYPE_LABELS: Record<string, string> = {
  episodic: '情景记忆',
  semantic: '语义记忆',
  procedural: '程序记忆',
}

const TYPE_COLORS: Record<string, string> = {
  episodic: '#2196F3',
  semantic: '#9C27B0',
  procedural: '#FF9800',
}

function importanceStars(importance: number): string {
  const stars = Math.min(Math.max(Math.round(importance * 5), 1), 5)
  return '★'.repeat(stars) + '☆'.repeat(5 - stars)
}

export function MemoryPanel({ onClose }: MemoryPanelProps) {
  const [stats, setStats] = useState<MemoryStatsData | null>(null)
  const [memories, setMemories] = useState<MemoryItem[]>([])
  const [activeTab, setActiveTab] = useState<'list' | 'search' | 'create'>(
    'list'
  )
  const [listType, setListType] = useState<string>('episodic')
  const [listLimit, setListLimit] = useState(20)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<MemoryItem[]>([])
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Create form state
  const [newContent, setNewContent] = useState('')
  const [newType, setNewType] = useState('episodic')
  const [newImportance, setNewImportance] = useState(0.5)
  const [creating, setCreating] = useState(false)

  // Expanded memory detail
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Operation status
  const [opMessage, setOpMessage] = useState<string | null>(null)

  const showMessage = (msg: string) => {
    setOpMessage(msg)
    setTimeout(() => setOpMessage(null), 3000)
  }

  const fetchStats = useCallback(async () => {
    const res = await api.getMemoryStats()
    if (res.status === 'ok' && res.data) {
      setStats(res.data as unknown as MemoryStatsData)
      setError(null)
    } else {
      setError(res.message || '获取统计失败')
    }
  }, [])

  const fetchMemories = useCallback(async () => {
    setLoading(true)
    setError(null)
    const res = await api.listMemories(listType, listLimit)
    if (res.status === 'ok' && res.data) {
      setMemories(res.data as unknown as MemoryItem[])
    } else {
      setError(res.message || '获取记忆列表失败')
    }
    setLoading(false)
  }, [listType, listLimit])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  useEffect(() => {
    if (activeTab === 'list') {
      fetchMemories()
    }
  }, [activeTab, fetchMemories])

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    setError(null)
    const res = await api.searchMemories(searchQuery, 10)
    if (res.status === 'ok' && res.data) {
      setSearchResults(res.data as unknown as MemoryItem[])
    } else {
      setError(res.message || '搜索失败')
    }
    setSearching(false)
  }

  const handleCreate = async () => {
    if (!newContent.trim()) return
    setCreating(true)
    setError(null)
    const res = await api.createMemory({
      content: newContent,
      type: newType,
      importance: newImportance,
    })
    if (res.status === 'ok') {
      showMessage('记忆创建成功！')
      setNewContent('')
      setNewImportance(0.5)
      fetchStats()
      if (activeTab === 'list') fetchMemories()
    } else {
      setError(res.message || '创建记忆失败')
    }
    setCreating(false)
  }

  const handleDelete = async (memoryId: string) => {
    if (!confirm('确定要删除这条记忆吗？')) return
    const res = await api.deleteMemory(memoryId)
    if (res.status === 'ok') {
      showMessage('记忆已删除')
      fetchStats()
      fetchMemories()
    } else {
      setError(res.message || '删除失败')
    }
  }

  const handleConsolidate = async () => {
    const res = await api.consolidateMemories()
    if (res.status === 'ok') {
      showMessage('记忆巩固已触发')
      fetchStats()
    } else {
      setError(res.message || '巩固操作失败')
    }
  }

  const handleForget = async () => {
    if (!confirm('确定要触发记忆遗忘？低重要性记忆将被清除。')) return
    const res = await api.forgetMemories()
    if (res.status === 'ok') {
      showMessage('记忆遗忘已触发')
      fetchStats()
      fetchMemories()
    } else {
      setError(res.message || '遗忘操作失败')
    }
  }

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  const renderMemoryCard = (memory: MemoryItem) => {
    const isExpanded = expandedId === memory.id
    return (
      <div
        key={memory.id}
        className={`memory-card ${isExpanded ? 'expanded' : ''}`}
      >
        <div className="memory-card-header" onClick={() => toggleExpand(memory.id)}>
          <span
            className="memory-type-badge"
            style={{ background: TYPE_COLORS[memory.type] || '#607D8B' }}
          >
            {TYPE_LABELS[memory.type] || memory.type}
          </span>
          <span
            className="memory-importance"
            title={`重要性: ${(memory.importance * 100).toFixed(0)}%`}
          >
            {importanceStars(memory.importance)}
          </span>
          <span className="memory-expand-icon">
            {isExpanded ? '▼' : '▶'}
          </span>
          <button
            className="memory-delete-btn"
            onClick={(e) => {
              e.stopPropagation()
              handleDelete(memory.id)
            }}
            title="删除"
          >
            ×
          </button>
        </div>

        <div className="memory-content">{memory.content}</div>

        {isExpanded && (
          <div className="memory-details">
            <div className="memory-detail-row">
              <span className="detail-label">ID:</span>
              <span className="detail-value">{memory.id}</span>
            </div>
            <div className="memory-detail-row">
              <span className="detail-label">创建时间:</span>
              <span className="detail-value">
                {new Date(memory.created_at).toLocaleString()}
              </span>
            </div>
            {memory.last_accessed && (
              <div className="memory-detail-row">
                <span className="detail-label">最后访问:</span>
                <span className="detail-value">
                  {new Date(memory.last_accessed).toLocaleString()}
                </span>
              </div>
            )}
            {memory.access_count != null && (
              <div className="memory-detail-row">
                <span className="detail-label">访问次数:</span>
                <span className="detail-value">{memory.access_count}</span>
              </div>
            )}
            {memory.metadata &&
              Object.keys(memory.metadata).length > 0 && (
                <div className="memory-detail-row">
                  <span className="detail-label">元数据:</span>
                  <pre className="detail-metadata">
                    {JSON.stringify(memory.metadata, null, 2)}
                  </pre>
                </div>
              )}
          </div>
        )}

        {!isExpanded && (
          <div className="memory-meta">
            <small>{new Date(memory.created_at).toLocaleString()}</small>
          </div>
        )}
      </div>
    )
  }

  const totalMemories = stats?.total_memories ?? stats?.total ?? 0

  return (
    <div className="memory-overlay">
      <div className="memory-panel">
        <div className="memory-panel-header">
          <h2>记忆系统</h2>
          <button className="memory-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        {error && <div className="memory-error">{error}</div>}
        {opMessage && <div className="memory-success">{opMessage}</div>}

        {/* Stats Section */}
        {stats && (
          <div className="memory-stats">
            <div className="stat-item stat-total">
              <div className="stat-number">{totalMemories}</div>
              <div className="stat-label">总记忆数</div>
            </div>
            {Object.entries(stats.by_type || {}).map(([type, count]) => (
              <div key={type} className="stat-item">
                <div
                  className="stat-number"
                  style={{ color: TYPE_COLORS[type] || '#607D8B' }}
                >
                  {count}
                </div>
                <div className="stat-label">
                  {TYPE_LABELS[type] || type}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Operation Buttons */}
        <div className="memory-operations">
          <button
            className="op-btn op-consolidate"
            onClick={handleConsolidate}
          >
            巩固记忆
          </button>
          <button className="op-btn op-forget" onClick={handleForget}>
            触发遗忘
          </button>
          <button
            className="op-btn op-refresh"
            onClick={() => {
              fetchStats()
              fetchMemories()
            }}
          >
            刷新
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="memory-tabs">
          <button
            className={`tab-btn ${activeTab === 'list' ? 'active' : ''}`}
            onClick={() => setActiveTab('list')}
          >
            记忆列表
          </button>
          <button
            className={`tab-btn ${activeTab === 'search' ? 'active' : ''}`}
            onClick={() => setActiveTab('search')}
          >
            搜索
          </button>
          <button
            className={`tab-btn ${activeTab === 'create' ? 'active' : ''}`}
            onClick={() => setActiveTab('create')}
          >
            创建记忆
          </button>
        </div>

        {/* Tab Content */}
        <div className="memory-tab-content">
          {activeTab === 'list' && (
            <div className="memory-list-tab">
              <div className="list-filters">
                <select
                  value={listType}
                  onChange={(e) => setListType(e.target.value)}
                >
                  {MEMORY_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {TYPE_LABELS[t]}
                    </option>
                  ))}
                </select>
                <select
                  value={listLimit}
                  onChange={(e) => setListLimit(Number(e.target.value))}
                >
                  <option value={10}>10 条</option>
                  <option value={20}>20 条</option>
                  <option value={50}>50 条</option>
                </select>
              </div>
              <div className="memory-list">
                {loading ? (
                  <div className="memory-loading">
                    <div className="loading-spinner" />
                    <p>加载中...</p>
                  </div>
                ) : memories.length === 0 ? (
                  <div className="memory-empty">暂无记忆</div>
                ) : (
                  memories.map(renderMemoryCard)
                )}
              </div>
            </div>
          )}

          {activeTab === 'search' && (
            <div className="memory-search-tab">
              <div className="search-bar">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder="输入搜索关键词..."
                />
                <button onClick={handleSearch} disabled={searching}>
                  {searching ? '搜索中...' : '搜索'}
                </button>
              </div>
              <div className="memory-list">
                {searchResults.length === 0 ? (
                  <div className="memory-empty">
                    {searchQuery ? '无搜索结果' : '输入关键词开始搜索'}
                  </div>
                ) : (
                  searchResults.map(renderMemoryCard)
                )}
              </div>
            </div>
          )}

          {activeTab === 'create' && (
            <div className="memory-create-tab">
              <div className="form-group">
                <label>记忆内容</label>
                <textarea
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  placeholder="输入记忆内容..."
                  rows={4}
                />
              </div>
              <div className="form-group">
                <label>类型</label>
                <select
                  value={newType}
                  onChange={(e) => setNewType(e.target.value)}
                >
                  {MEMORY_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {TYPE_LABELS[t]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>
                  重要性: {(newImportance * 100).toFixed(0)}%
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={newImportance}
                  onChange={(e) =>
                    setNewImportance(Number(e.target.value))
                  }
                />
                <div className="importance-scale">
                  <span>低</span>
                  <span>中</span>
                  <span>高</span>
                </div>
              </div>
              <button
                className="create-btn"
                onClick={handleCreate}
                disabled={creating || !newContent.trim()}
              >
                {creating ? '创建中...' : '创建记忆'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
