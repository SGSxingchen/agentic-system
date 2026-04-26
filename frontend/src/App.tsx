import { useState, useCallback, useMemo } from 'react'
import { AppProvider, useAppStore } from './store/appStore'
import { useWebSocket } from './hooks/useWebSocket'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'
import { AgentPanel } from './components/AgentPanel'
import { MemoryPanel } from './components/MemoryPanel'
import { MonitorPanel } from './components/MonitorPanel'
import { TaskPanel } from './components/TaskPanel'
import { PipelinePanel } from './components/PipelinePanel'
import { EvolutionPanel } from './components/EvolutionPanel'
import { Settings } from './components/Settings'
import type { WSEvent, Message } from './types'
import './App.css'

function AppContent() {
  const { state, dispatch } = useAppStore()
  const [showSettings, setShowSettings] = useState(false)
  const [showMemory, setShowMemory] = useState(false)

  const handleWSMessage = useCallback(
    (raw: unknown) => {
      const event = raw as WSEvent
      dispatch({ type: 'ADD_WS_EVENT', payload: event })

      // Handle specific event types
      const eventType = event.event_type || event.type

      if (eventType === 'assistant_response' && event.data) {
        const msg: Message = {
          id: `ws-assistant-${Date.now()}`,
          type: 'assistant',
          content:
            event.data.response ||
            event.data.content ||
            event.data.message ||
            JSON.stringify(event.data),
          timestamp: event.timestamp,
          memoriesUsed:
            event.data.memories_used || event.data.memory_count || 0,
        }
        dispatch({ type: 'ADD_MESSAGE', payload: msg })
      }

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

  const wsUrl = useMemo(() => `ws://${window.location.host}/ws`, [])

  useWebSocket({
    url: wsUrl,
    onMessage: handleWSMessage,
    onConnect: handleWSConnect,
    onDisconnect: handleWSDisconnect,
  })

  const renderPanel = () => {
    switch (state.activePanel) {
      case 'chat':
        return <ChatPanel />
      case 'tasks':
        return <TaskPanel />
      case 'agents':
        return <AgentPanel />
      case 'pipeline':
        return <PipelinePanel />
      case 'evolution':
        return <EvolutionPanel />
      case 'memory':
        return (
          <div className="memory-panel-inline">
            <div className="panel-header">
              <h2>记忆管理</h2>
              <button
                className="open-modal-btn"
                onClick={() => setShowMemory(true)}
              >
                详细管理
              </button>
            </div>
            <div className="memory-panel-hint">
              <p>点击 "详细管理" 打开完整的记忆管理面板</p>
              <button
                className="open-modal-btn-large"
                onClick={() => setShowMemory(true)}
              >
                打开记忆管理面板
              </button>
            </div>
          </div>
        )
      case 'monitor':
        return <MonitorPanel />
      default:
        return <ChatPanel />
    }
  }

  return (
    <div className="app-layout">
      <Sidebar onOpenSettings={() => setShowSettings(true)} />
      <main className="main-content">{renderPanel()}</main>

      {showSettings && (
        <Settings onClose={() => setShowSettings(false)} />
      )}
      {showMemory && (
        <MemoryPanel onClose={() => setShowMemory(false)} />
      )}
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
