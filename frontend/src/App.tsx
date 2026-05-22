import { useCallback, useEffect, useMemo, useState } from 'react'
import { AppProvider, useAppStore } from './store/appStore'
import { useWebSocket } from './hooks/useWebSocket'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { OverviewPanel } from './components/OverviewPanel'
import { WorkspacePanel } from './components/WorkspacePanel'
import { AgentPanel } from './components/AgentPanel'
import { RunsPanel } from './components/RunsPanel'
import { MonitorPanel } from './components/MonitorPanel'
import { MemoryPanel } from './components/MemoryPanel'
import { PersonaPanel } from './components/PersonaPanel'
import { Settings } from './components/Settings'
import * as api from './api/client'
import type { WSEvent } from './types'
import './App.css'

function AppContent() {
  const { state, dispatch } = useAppStore()
  const [showSettings, setShowSettings] = useState(false)

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
    return `${protocol}//${window.location.host}/ws`
  }, [])

  useWebSocket({
    url: wsUrl,
    onMessage: handleWSMessage,
    onConnect: handleWSConnect,
    onDisconnect: handleWSDisconnect,
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
    switch (state.activePanel) {
      case 'overview':
        return <OverviewPanel />
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
      case 'personas':
        return <PersonaPanel />
      default:
        return <OverviewPanel />
    }
  }

  const titleByPanel: Record<string, string> = {
    overview: '总览',
    workspaces: '工作区',
    agents: '智能体',
    runs: '运行',
    monitor: '监控',
    memory: '记忆',
    personas: '人格',
  }

  return (
    <div className="app-layout">
      <Sidebar onOpenSettings={() => setShowSettings(true)} />
      <div className="main-column">
        <Topbar pageTitle={titleByPanel[state.activePanel] || '工作台'} />
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
