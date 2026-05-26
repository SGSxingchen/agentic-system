import { useAppStore } from '../store/appStore'
import type { PanelType } from '../types'
import './Sidebar.css'

interface NavItem {
  key: PanelType
  icon: React.ReactNode
  label: string
}

const Icon = {
  overview: (
    <svg viewBox="0 0 24 24">
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  ),
  chat: (
    <svg viewBox="0 0 24 24">
      <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  chatroom: (
    <svg viewBox="0 0 24 24">
      <circle cx="8" cy="9" r="3" />
      <circle cx="16" cy="9" r="3" />
      <circle cx="12" cy="15" r="3" />
    </svg>
  ),
  workspaces: (
    <svg viewBox="0 0 24 24">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  ),
  agents: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="8" r="4" />
      <path d="M20 21a8 8 0 1 0-16 0" />
    </svg>
  ),
  runs: (
    <svg viewBox="0 0 24 24">
      <polyline points="5 4 19 12 5 20 5 4" />
    </svg>
  ),
  monitor: (
    <svg viewBox="0 0 24 24">
      <rect x="3" y="4" width="18" height="13" rx="1" />
      <path d="M8 20h8" />
      <path d="M12 17v3" />
      <polyline points="6 12 9 9 12 12 18 6" />
    </svg>
  ),
  memory: (
    <svg viewBox="0 0 24 24">
      <path d="M5 5h11l3 3v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />
      <path d="M8 9h8" />
      <path d="M8 13h8" />
      <path d="M8 17h5" />
    </svg>
  ),
  skills: (
    <svg viewBox="0 0 24 24">
      <path d="M12 2l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 14.3 7.2 16.9l.9-5.4L4.2 7.7l5.4-.8z" />
    </svg>
  ),
  mcp: (
    <svg viewBox="0 0 24 24">
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <circle cx="12" cy="18" r="2.5" />
      <path d="M6 8.5v3a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-3" />
      <path d="M12 13.5v2" />
    </svg>
  ),
  personas: (
    <svg viewBox="0 0 24 24">
      <path d="M12 3l8 4v5c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V7l8-4z" />
      <circle cx="12" cy="11" r="2" />
      <path d="M9 17c0-1.7 1.3-3 3-3s3 1.3 3 3" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12c0-.4 0-.7-.1-1l2-1.6-2-3.4-2.3.9c-.5-.4-1.1-.7-1.7-1L14.5 3h-5l-.4 2.9c-.6.2-1.2.5-1.7 1l-2.3-.9-2 3.4 2 1.6c-.1.3-.1.6-.1 1s0 .7.1 1l-2 1.6 2 3.4 2.3-.9c.5.4 1.1.7 1.7 1L9.5 21h5l.4-2.9c.6-.2 1.2-.5 1.7-1l2.3.9 2-3.4-2-1.6c.1-.3.1-.7.1-1z" />
    </svg>
  ),
}

const NAV_SECTIONS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: '工作台',
    items: [
      { key: 'overview', icon: Icon.overview, label: '总览' },
      { key: 'chat', icon: Icon.chat, label: '对话' },
      { key: 'chatroom', icon: Icon.chatroom, label: '聊天室' },
      { key: 'workspaces', icon: Icon.workspaces, label: '工作区' },
    ],
  },
  {
    label: '智能体',
    items: [
      { key: 'agents', icon: Icon.agents, label: '智能体' },
      { key: 'runs', icon: Icon.runs, label: '运行' },
      { key: 'monitor', icon: Icon.monitor, label: '监控' },
    ],
  },
  {
    label: '能力与扩展',
    items: [
      { key: 'skills', icon: Icon.skills, label: 'Skills' },
      { key: 'mcp', icon: Icon.mcp, label: 'MCP' },
    ],
  },
  {
    label: '资料与角色',
    items: [
      { key: 'memory', icon: Icon.memory, label: '记忆' },
      { key: 'personas', icon: Icon.personas, label: '人格' },
    ],
  },
]

interface SidebarProps {
  onOpenSettings: () => void
}

export function Sidebar({ onOpenSettings }: SidebarProps) {
  const { state, dispatch } = useAppStore()

  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="sidebar__brand-mark">A</div>
        <div className="sidebar__brand-text">
          <strong>Agent Studio</strong>
          <span>多 Agent 工作台</span>
        </div>
      </div>

      <nav className="sidebar__nav">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div className="sidebar__section-label">{section.label}</div>
            {section.items.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`sidebar__nav-item ${
                  state.activePanel === item.key ? 'sidebar__nav-item--active' : ''
                }`}
                onClick={() => dispatch({ type: 'SET_ACTIVE_PANEL', payload: item.key })}
              >
                <span className="sidebar__nav-icon">{item.icon}</span>
                <span className="sidebar__nav-label">{item.label}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar__footer">
        <button type="button" className="sidebar__settings-btn" onClick={onOpenSettings}>
          {Icon.settings}
          <span>设置</span>
        </button>
      </div>
    </aside>
  )
}
