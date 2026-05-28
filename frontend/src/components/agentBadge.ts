// Helpers for resolving an agent display name + LLM model badge from a sender id.
//
// Sender ids in the chat protocols:
//   - 'user'         → { name: '用户' }
//   - 'system'       → { name: '系统' }
//   - 'agent:<name>' → { name, model? }   model looked up from agentMeta map
//
// B4 — 2026-05-28 自由化与 UI 增强 plan, Task 2.

export interface AgentMetaEntry {
  model?: string
}

export type AgentMetaMap = Record<string, AgentMetaEntry>

export interface SenderDisplay {
  name: string
  model?: string
}

export function senderToDisplay(
  sender: string,
  agentMeta: AgentMetaMap = {},
): SenderDisplay {
  if (sender === 'user') return { name: '用户' }
  if (sender === 'system') return { name: '系统' }
  if (sender.startsWith('agent:')) {
    const name = sender.slice(6) || 'agent'
    const model = agentMeta[name]?.model
    return model ? { name, model } : { name }
  }
  return { name: sender || 'unknown' }
}

interface AgentLike {
  name: string
  model?: string | null
}

export function agentMetaFromList(agents: AgentLike[]): AgentMetaMap {
  const out: AgentMetaMap = {}
  for (const a of agents) {
    if (!a || !a.name) continue
    if (a.model) {
      out[a.name] = { model: String(a.model) }
    } else {
      out[a.name] = {}
    }
  }
  return out
}
