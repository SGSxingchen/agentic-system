import {
  createContext,
  useContext,
  useReducer,
  type ReactNode,
  type Dispatch,
} from 'react'
import type {
  AgentInfo,
  MemoryStats,
  LLMConfig,
  HealthStatus,
  WSEvent,
  PanelType,
  Persona,
  PersonaBindings,
  ManagedWorkspace,
} from '../types'

// ===== State =====

export interface SelectedWorkspaceRef {
  id: string
  name: string
}

export interface AppState {
  agents: AgentInfo[]
  memoryStats: MemoryStats | null
  config: LLMConfig | null
  health: HealthStatus | null
  connected: boolean
  activePanel: PanelType
  wsEvents: WSEvent[]
  workspaces: ManagedWorkspace[]
  selectedWorkspace: SelectedWorkspaceRef | null
  personaCache: {
    personas: Persona[]
    includeArchived: boolean
    personasFetchedAt: number
    bindings: PersonaBindings | null
    bindingsFetchedAt: number
  }
}

const SELECTED_WORKSPACE_KEY = 'agentic.selectedWorkspace'

function readPersistedWorkspace(): SelectedWorkspaceRef | null {
  try {
    const raw = window.localStorage.getItem(SELECTED_WORKSPACE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed.id === 'string' && typeof parsed.name === 'string') {
      return parsed as SelectedWorkspaceRef
    }
  } catch {
    // ignore SSR / quota / parse failures
  }
  return null
}

function writePersistedWorkspace(value: SelectedWorkspaceRef | null) {
  try {
    if (value) {
      window.localStorage.setItem(SELECTED_WORKSPACE_KEY, JSON.stringify(value))
    } else {
      window.localStorage.removeItem(SELECTED_WORKSPACE_KEY)
    }
  } catch {
    // ignore
  }
}

const initialState: AppState = {
  agents: [],
  memoryStats: null,
  config: null,
  health: null,
  connected: false,
  activePanel: 'overview',
  wsEvents: [],
  workspaces: [],
  selectedWorkspace: typeof window !== 'undefined' ? readPersistedWorkspace() : null,
  personaCache: {
    personas: [],
    includeArchived: false,
    personasFetchedAt: 0,
    bindings: null,
    bindingsFetchedAt: 0,
  },
}

// ===== Actions =====

export type AppAction =
  | { type: 'SET_AGENTS'; payload: AgentInfo[] }
  | { type: 'SET_MEMORY_STATS'; payload: MemoryStats | null }
  | { type: 'SET_CONFIG'; payload: LLMConfig | null }
  | { type: 'SET_HEALTH'; payload: HealthStatus | null }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_ACTIVE_PANEL'; payload: PanelType }
  | { type: 'ADD_WS_EVENT'; payload: WSEvent }
  | { type: 'CLEAR_WS_EVENTS' }
  | { type: 'UPDATE_AGENT_STATUS'; payload: { name: string; status: AgentInfo['status'] } }
  | { type: 'SET_WORKSPACES'; payload: ManagedWorkspace[] }
  | { type: 'SET_SELECTED_WORKSPACE'; payload: SelectedWorkspaceRef | null }
  | { type: 'SET_PERSONAS_CACHE'; payload: { personas: Persona[]; includeArchived: boolean; fetchedAt?: number } }
  | { type: 'SET_PERSONA_BINDINGS_CACHE'; payload: { bindings: PersonaBindings; fetchedAt?: number } }
  | { type: 'INVALIDATE_PERSONA_CACHE' }

// ===== Reducer =====

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
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
    case 'UPDATE_AGENT_STATUS':
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.name === action.payload.name
            ? { ...a, status: action.payload.status }
            : a
        ),
      }
    case 'SET_WORKSPACES': {
      const workspaces = action.payload
      let selected = state.selectedWorkspace
      if (selected && !workspaces.some((w) => w.id === selected!.id)) {
        selected = null
        writePersistedWorkspace(null)
      } else if (selected) {
        const match = workspaces.find((w) => w.id === selected!.id)
        if (match && match.name !== selected.name) {
          selected = { id: match.id, name: match.name }
          writePersistedWorkspace(selected)
        }
      }
      return { ...state, workspaces, selectedWorkspace: selected }
    }
    case 'SET_SELECTED_WORKSPACE':
      writePersistedWorkspace(action.payload)
      return { ...state, selectedWorkspace: action.payload }
    case 'SET_PERSONAS_CACHE':
      return {
        ...state,
        personaCache: {
          ...state.personaCache,
          personas: action.payload.personas,
          includeArchived: action.payload.includeArchived,
          personasFetchedAt: action.payload.fetchedAt ?? Date.now(),
        },
      }
    case 'SET_PERSONA_BINDINGS_CACHE':
      return {
        ...state,
        personaCache: {
          ...state.personaCache,
          bindings: action.payload.bindings,
          bindingsFetchedAt: action.payload.fetchedAt ?? Date.now(),
        },
      }
    case 'INVALIDATE_PERSONA_CACHE':
      return {
        ...state,
        personaCache: {
          ...state.personaCache,
          personasFetchedAt: 0,
          bindingsFetchedAt: 0,
        },
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
