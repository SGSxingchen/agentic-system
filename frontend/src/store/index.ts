import type { Task, AgentInfo, Memory, WSEvent, ViewType } from '../types'

export interface AppState {
  tasks: Task[]
  agents: AgentInfo[]
  memories: Memory[]
  events: WSEvent[]
  connected: boolean
  currentView: ViewType
  loading: boolean
  error: string | null
}

export type AppAction =
  | { type: 'SET_TASKS'; payload: Task[] }
  | { type: 'ADD_TASK'; payload: Task }
  | { type: 'UPDATE_TASK'; payload: Task }
  | { type: 'REMOVE_TASK'; payload: string }
  | { type: 'SET_AGENTS'; payload: AgentInfo[] }
  | { type: 'SET_MEMORIES'; payload: Memory[] }
  | { type: 'ADD_EVENT'; payload: WSEvent }
  | { type: 'SET_EVENTS'; payload: WSEvent[] }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_VIEW'; payload: ViewType }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }

export const initialState: AppState = {
  tasks: [],
  agents: [],
  memories: [],
  events: [],
  connected: false,
  currentView: 'dashboard',
  loading: false,
  error: null,
}

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_TASKS':
      return { ...state, tasks: action.payload }
    case 'ADD_TASK':
      return { ...state, tasks: [action.payload, ...state.tasks] }
    case 'UPDATE_TASK': {
      const taskId = action.payload.task_id || action.payload.id
      return {
        ...state,
        tasks: state.tasks.map(t =>
          (t.task_id || t.id) === taskId ? action.payload : t
        ),
      }
    }
    case 'REMOVE_TASK':
      return {
        ...state,
        tasks: state.tasks.filter(t => (t.task_id || t.id) !== action.payload),
      }
    case 'SET_AGENTS':
      return { ...state, agents: action.payload }
    case 'SET_MEMORIES':
      return { ...state, memories: action.payload }
    case 'ADD_EVENT':
      return { ...state, events: [...state.events, action.payload] }
    case 'SET_EVENTS':
      return { ...state, events: action.payload }
    case 'SET_CONNECTED':
      return { ...state, connected: action.payload }
    case 'SET_VIEW':
      return { ...state, currentView: action.payload }
    case 'SET_LOADING':
      return { ...state, loading: action.payload }
    case 'SET_ERROR':
      return { ...state, error: action.payload }
    default:
      return state
  }
}
