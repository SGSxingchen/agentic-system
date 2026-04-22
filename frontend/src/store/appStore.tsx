import {
  createContext,
  useContext,
  useReducer,
  type ReactNode,
  type Dispatch,
} from 'react'
import type {
  Message,
  AgentInfo,
  MemoryStats,
  LLMConfig,
  HealthStatus,
  WSEvent,
  PanelType,
} from '../types'

// ===== State =====

export interface AppState {
  messages: Message[]
  agents: AgentInfo[]
  memoryStats: MemoryStats | null
  config: LLMConfig | null
  health: HealthStatus | null
  connected: boolean
  activePanel: PanelType
  wsEvents: WSEvent[]
  sending: boolean
}

const initialState: AppState = {
  messages: [],
  agents: [],
  memoryStats: null,
  config: null,
  health: null,
  connected: false,
  activePanel: 'chat',
  wsEvents: [],
  sending: false,
}

// ===== Actions =====

export type AppAction =
  | { type: 'ADD_MESSAGE'; payload: Message }
  | { type: 'SET_MESSAGES'; payload: Message[] }
  | { type: 'SET_AGENTS'; payload: AgentInfo[] }
  | { type: 'SET_MEMORY_STATS'; payload: MemoryStats | null }
  | { type: 'SET_CONFIG'; payload: LLMConfig | null }
  | { type: 'SET_HEALTH'; payload: HealthStatus | null }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_ACTIVE_PANEL'; payload: PanelType }
  | { type: 'ADD_WS_EVENT'; payload: WSEvent }
  | { type: 'CLEAR_WS_EVENTS' }
  | { type: 'SET_SENDING'; payload: boolean }
  | { type: 'UPDATE_AGENT_STATUS'; payload: { name: string; status: AgentInfo['status'] } }

// ===== Reducer =====

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.payload] }
    case 'SET_MESSAGES':
      return { ...state, messages: action.payload }
    case 'SET_AGENTS':
      return { ...state, agents: action.payload }
    case 'SET_MEMORY_STATS':
      return { ...state, memoryStats: action.payload }
    case 'SET_CONFIG':
      return { ...state, config: action.payload }
    case 'SET_HEALTH':
      return { ...state, health: action.payload }
    case 'SET_CONNECTED':
      return { ...state, connected: action.payload }
    case 'SET_ACTIVE_PANEL':
      return { ...state, activePanel: action.payload }
    case 'ADD_WS_EVENT':
      return {
        ...state,
        wsEvents: [...state.wsEvents.slice(-199), action.payload],
      }
    case 'CLEAR_WS_EVENTS':
      return { ...state, wsEvents: [] }
    case 'SET_SENDING':
      return { ...state, sending: action.payload }
    case 'UPDATE_AGENT_STATUS':
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.name === action.payload.name
            ? { ...a, status: action.payload.status }
            : a
        ),
      }
    default:
      return state
  }
}

// ===== Context =====

interface AppContextType {
  state: AppState
  dispatch: Dispatch<AppAction>
}

const AppContext = createContext<AppContextType | null>(null)

// ===== Provider =====

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState)

  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  )
}

// ===== Hook =====

export function useAppStore(): AppContextType {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error('useAppStore must be used within AppProvider')
  }
  return context
}
