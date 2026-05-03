import { useAppStore } from '../store/appStore'
import type { PanelType } from '../types'
import './Sidebar.css'

interface NavItem {
  key: PanelType
  icon: React.ReactNode
  label: string
}

// SVG icons (simple line icons)
const Icons = {
  chat: (
    <svg viewBox="0 0 24 24">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  tasks: (
    <svg viewBox="0 0 24 24">
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  ),
  agents: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="8" r="4" />
      <path d="M20 21a8 8 0 1 0-16 0" />
    </svg>
  ),
  pipeline: (
    <svg viewBox="0 0 24 24">
      <polyline points="16 3 21 3 21 8" />
      <line x1="4" y1="20" x2="21" y2="3" />
      <polyline points="21 16 21 21 16 21" />
      <line x1="15" y1="15" x2="21" y2="21" />
      <line x1="4" y1="4" x2="9" y2="9" />
    </svg>
  ),
  memory: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </svg>
  ),
  monitor: (
    <svg viewBox="0 0 24 24">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  ),
  evolution: (
    <svg viewBox="0 0 24 24">
      <path d="M12 2v5" />
      <path d="M12 17v5" />
      <path d="M4.22 4.22l3.54 3.54" />
      <path d="M16.24 16.24l3.54 3.54" />
      <path d="M2 12h5" />
      <path d="M17 12h5" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </svg>
  ),
  personas: (
    <svg viewBox="0 0 24 24">
      <path d="M12 3l7 4v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V7l7-4z" />
      <path d="M9 12h6" />
      <path d="M9 16h6" />
      <path d="M10 8h4" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
}

const NAV_ITEMS: NavItem[] = [
  { key: 'chat', icon: Icons.chat, label: '对话' },
  { key: 'tasks', icon: Icons.tasks, label: '任务' },
  { key: 'agents', icon: Icons.agents, label: '智能体' },
  { key: 'pipeline', icon: Icons.pipeline, label: '管线' },
  { key: 'memory', icon: Icons.memory, label: '记忆' },
  { key: 'evolution', icon: Icons.evolution, label: '进化' },
  { key: 'personas', icon: Icons.personas, label: '人格' },
  { key: 'monitor', icon: Icons.monitor, label: '监控' },
]

interface SidebarProps {
  onOpenSettings: () => void
}

export function Sidebar({ onOpenSettings }: SidebarProps) {
  const { state, dispatch } = useAppStore()

  return (
    <aside className="sidebar">
      {/* Logo / Title */}
      <div className="sidebar-header">
        <div className="sidebar-logo">M</div>
        <div className="sidebar-title">
          <h1>Multi-Agent</h1>
          <span>System</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            className={`sidebar-nav-item ${
              state.activePanel === item.key ? 'active' : ''
            }`}
            onClick={() =>
              dispatch({ type: 'SET_ACTIVE_PANEL', payload: item.key })
            }
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        <div
          className={`sidebar-status ${
            state.connected ? 'connected' : 'disconnected'
          }`}
        >
          <span className="status-dot" />
          <span className="status-text">
            {state.connected ? '已连接' : '未连接'}
          </span>
        </div>
        <button className="sidebar-settings-btn" onClick={onOpenSettings}>
          {Icons.settings}
          <span>设置</span>
        </button>
      </div>
    </aside>
  )
}
