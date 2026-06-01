import { useCallback, useEffect, useMemo, useState } from 'react'
import { AppProvider, useAppStore } from './store/appStore'
import { useWebSocket } from './hooks/useWebSocket'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { OverviewPanel } from './components/OverviewPanel'
import { ChatPanel } from './components/ChatPanel'
import { ChatroomPanel } from './components/ChatroomPanel'
import { WorkspacePanel } from './components/WorkspacePanel'
import { AgentPanel } from './components/AgentPanel'
import { RunsPanel } from './components/RunsPanel'
import { MonitorPanel } from './components/MonitorPanel'
import { MemoryPanel } from './components/MemoryPanel'
import { ToolsPanel } from './components/ToolsPanel'
import { SkillsPanel } from './components/SkillsPanel'
import { McpPanel } from './components/McpPanel'
import { PersonaPanel } from './components/PersonaPanel'
import { Settings } from './components/Settings'
import { LoginPage } from './components/LoginPage'
import * as api from './api/client'
import type { WSEvent } from './types'
import './App.css'

function AppContent() {
  const { state, dispatch } = useAppStore()
  const [showSettings, setShowSettings] = useState(false)
  // A11: 全局密码门禁登录态。token 缺失时挂 LoginPage，输入正确密码后切到主面板。
  // - 初始读 localStorage（getAuthToken）
  // - 401 时 client.ts 派发 'agentic:auth-failed' → 我们清状态退到登录页
  const [authToken, setAuthTokenState] = useState<string | null>(() =>
    api.getAuthToken()
  )
  const isAuthed = authToken !== null && authToken !== ''

  useEffect(() => {
    const onAuthFailed = () => setAuthTokenState(null)
    window.addEventListener(api.AUTH_FAILED_EVENT, onAuthFailed)
    return () => {
      window.removeEventListener(api.AUTH_FAILED_EVENT, onAuthFailed)
    }
  }, [])

  const handleWSMessage = useCallback(
    (raw: unknown) => {
      const event = raw as WSEvent
      dispatch({ type: 'ADD_WS_EVENT', payload: event })

      const eventType = event.event_type || event.type

      if (eventType === 'agent_status_update' && event.data) {
        dispatch({
          type: 'UPDATE_AGENT_STATUS',
          payload: {
            name: event.data.agent || event.data.name,
            status: event.data.status,
          },
        })
      }
    },
    [dispatch]
  )

  const handleWSConnect = useCallback(() => {
    dispatch({ type: 'SET_CONNECTED', payload: true })
  }, [dispatch])

  const handleWSDisconnect = useCallback(() => {
    dispatch({ type: 'SET_CONNECTED', payload: false })
  }, [dispatch])

  const wsUrl = useMemo(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // A11: 后端开了 access_password 时，WS 必须带 ?token=<password>，否则会被 close(4401)。
    // 这里读最新 token；未登录时不连 WS（依然返回有意义的 url 防 hook 类型变化，但 isAuthed 守卫会跳过）。
    const token = authToken || ''
    const tokenSuffix = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${protocol}//${window.location.host}/ws${tokenSuffix}`
  }, [authToken])

  // 未登录时不连 WS — 用空 url 让 useWebSocket 内部 new WebSocket('') 抛错快速失败也行，
  // 但更干净的方式是 conditional rendering：登录前根本不挂 AppContent 的 WS hook。
  // 这里走第二条路：把 WS hook 包在一个 children-component 里，根据 isAuthed 切换。
  return isAuthed ? (
    <AuthenticatedApp
      wsUrl={wsUrl}
      onWSMessage={handleWSMessage}
      onWSConnect={handleWSConnect}
      onWSDisconnect={handleWSDisconnect}
      showSettings={showSettings}
      setShowSettings={setShowSettings}
      activePanel={state.activePanel}
    />
  ) : (
    <LoginPage onLogin={() => setAuthTokenState(api.getAuthToken())} />
  )
}

interface AuthenticatedAppProps {
  wsUrl: string
  onWSMessage: (raw: unknown) => void
  onWSConnect: () => void
  onWSDisconnect: () => void
  showSettings: boolean
  setShowSettings: (v: boolean) => void
  activePanel: string
}

function AuthenticatedApp({
  wsUrl,
  onWSMessage,
  onWSConnect,
  onWSDisconnect,
  showSettings,
  setShowSettings,
  activePanel,
}: AuthenticatedAppProps) {
  const { dispatch } = useAppStore()

  useWebSocket({
    url: wsUrl,
    onMessage: onWSMessage,
    onConnect: onWSConnect,
    onDisconnect: onWSDisconnect,
  })

  // Load workspaces & health on mount
  useEffect(() => {
    let cancelled = false

    const loadWorkspaces = async () => {
      const res = await api.listWorkspaces()
      if (cancelled) return
      if (res.status === 'ok' && Array.isArray(res.data)) {
        dispatch({ type: 'SET_WORKSPACES', payload: res.data })
      }
    }
    const loadHealth = async () => {
      const res = await api.getHealth()
      if (cancelled) return
      if (res.status === 'ok' && res.data) {
        dispatch({ type: 'SET_HEALTH', payload: res.data })
      }
    }

    loadWorkspaces()
    loadHealth()
    const t = window.setInterval(loadHealth, 15_000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [dispatch])

  const renderPanel = () => {
    switch (activePanel) {
      case 'overview':
        return <OverviewPanel />
      case 'chat':
        return <ChatPanel />
      case 'chatroom':
        return <ChatroomPanel />
      case 'workspaces':
        return <WorkspacePanel />
      case 'agents':
        return <AgentPanel />
      case 'runs':
        return <RunsPanel />
      case 'monitor':
        return <MonitorPanel />
      case 'memory':
        return <MemoryPanel />
      case 'tools':
        return <ToolsPanel />
      case 'skills':
        return <SkillsPanel />
      case 'mcp':
        return <McpPanel />
      case 'personas':
        return <PersonaPanel />
      default:
        return <OverviewPanel />
    }
  }

  const titleByPanel: Record<string, string> = {
    overview: '总览',
    chat: '对话',
    chatroom: '聊天室',
    workspaces: '工作区',
    agents: '智能体',
    runs: '运行',
    monitor: '监控',
    memory: '记忆',
    tools: '工具',
    skills: 'Skills',
    mcp: 'MCP',
    personas: '人格',
  }

  return (
    <div className="app-layout">
      <Sidebar onOpenSettings={() => setShowSettings(true)} />
      <div className="main-column">
        <Topbar pageTitle={titleByPanel[activePanel] || '工作台'} />
        <main className="main-content">{renderPanel()}</main>
      </div>

      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
    </div>
  )
}

function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  )
}

export default App
