import { useState, useEffect, useRef, useCallback } from 'react'
import { useAppStore } from '../store/appStore'
import type {
  AgentProgressEvent,
  ChatSession,
  ChatSessionSummary,
  Message,
  TokenUsage,
  ToolCallRecord,
  MessageTimelineItem,
} from '../types'
import {
  addChatSessionMessage,
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
} from '../api/client'
import {
  appendTextTimelineItem,
  getMessageTimeline,
  updateToolResultTimelineItem,
  upsertToolCallTimelineItem,
} from '../utils/messageTimeline'
import './ChatPanel.css'

const API_BASE = ''

// ===== Markdown Renderer =====

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeMarkdownUrl(url: string): string {
  const clean = url.trim()
  if (/^(https?:|mailto:|#|\/)/i.test(clean)) {
    return escapeHtml(clean)
  }
  return '#'
}

function renderInlineMarkdown(text: string): string {
  const codeSpans: string[] = []
  let html = text.replace(/`([^`]+)`/g, (_match, code) => {
    const index = codeSpans.push(`<code class="md-inline-code">${escapeHtml(code)}</code>`) - 1
    return `\uE000${index}\uE001`
  })

  html = escapeHtml(html)
  html = html.replace(
    /!\[([^\]]*)\]\(([^)\s]+)\)/g,
    (_match, alt, url) =>
      `<img class="md-image" src="${sanitizeMarkdownUrl(url)}" alt="${alt}" loading="lazy" />`
  )
  html = html.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_match, label, url) =>
      `<a href="${sanitizeMarkdownUrl(url)}" target="_blank" rel="noreferrer">${label}</a>`
  )
  html = html.replace(/~~(.+?)~~/g, '<del>$1</del>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
  html = html.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, '$1<em>$2</em>')

  codeSpans.forEach((code, index) => {
    html = html.split(`\uE000${index}\uE001`).join(code)
  })
  return html
}

function isTableDivider(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line)
}

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isMarkdownBlockStart(line: string, nextLine?: string): boolean {
  const trimmed = line.trim()
  return (
    trimmed.startsWith('```') ||
    /^#{1,6}\s+/.test(trimmed) ||
    /^-{3,}$/.test(trimmed) ||
    /^>\s?/.test(trimmed) ||
    /^[-*+]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed) ||
    (!!nextLine && trimmed.includes('|') && isTableDivider(nextLine))
  )
}

function renderMarkdown(text: string): string {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    const trimmed = line.trim()

    if (!trimmed) {
      index += 1
      continue
    }

    if (trimmed.startsWith('```')) {
      const language = trimmed.slice(3).trim().replace(/[^\w-]/g, '')
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      const languageClass = language ? ` language-${escapeHtml(language)}` : ''
      html.push(
        `<pre class="md-code-block"><code class="${languageClass.trim()}">${escapeHtml(codeLines.join('\n'))}</code></pre>`
      )
      continue
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    if (/^-{3,}$/.test(trimmed)) {
      html.push('<hr class="md-hr" />')
      index += 1
      continue
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ''))
        index += 1
      }
      html.push(`<blockquote>${quoteLines.map(renderInlineMarkdown).join('<br/>')}</blockquote>`)
      continue
    }

    if (/^[-*+]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      const ordered = /^\d+\.\s+/.test(trimmed)
      const markerPattern = ordered ? /^\d+\.\s+/ : /^[-*+]\s+/
      const items: string[] = []
      while (
        index < lines.length &&
        markerPattern.test(lines[index].trim())
      ) {
        const itemText = lines[index].trim().replace(markerPattern, '')
        const task = itemText.match(/^\[( |x|X)\]\s+(.+)$/)
        if (task) {
          const checked = task[1].toLowerCase() === 'x' ? ' checked' : ''
          items.push(
            `<li class="md-task-item"><input type="checkbox" disabled${checked} /> <span>${renderInlineMarkdown(task[2])}</span></li>`
          )
        } else {
          items.push(`<li>${renderInlineMarkdown(itemText)}</li>`)
        }
        index += 1
      }
      html.push(`<${ordered ? 'ol' : 'ul'}>${items.join('')}</${ordered ? 'ol' : 'ul'}>`)
      continue
    }

    if (trimmed.includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headers = splitTableRow(trimmed)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && lines[index].trim().includes('|')) {
        rows.push(splitTableRow(lines[index]))
        index += 1
      }
      html.push(
        `<div class="md-table-wrapper"><table><thead><tr>${headers
          .map((header) => `<th>${renderInlineMarkdown(header)}</th>`)
          .join('')}</tr></thead><tbody>${rows
          .map(
            (row) =>
              `<tr>${headers
                .map((_header, cellIndex) => `<td>${renderInlineMarkdown(row[cellIndex] || '')}</td>`)
                .join('')}</tr>`
          )
          .join('')}</tbody></table></div>`
      )
      continue
    }

    const paragraphLines: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isMarkdownBlockStart(lines[index], lines[index + 1])
    ) {
      paragraphLines.push(lines[index].trim())
      index += 1
    }
    html.push(`<p>${renderInlineMarkdown(paragraphLines.join(' '))}</p>`)
  }

  return html.join('')
}

function summarizeSession(session: ChatSession): ChatSessionSummary {
  const lastMessage = session.messages[session.messages.length - 1]
  return {
    id: session.id,
    title: session.title,
    created_at: session.created_at,
    updated_at: session.updated_at,
    message_count: session.messages.length,
    last_message: lastMessage?.content || '',
  }
}

function formatSessionTime(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function buildContextMessages(messages: Message[]): { role: 'user' | 'assistant'; content: string }[] {
  return messages
    .filter((message) => (
      (message.type === 'user' || message.type === 'assistant') &&
      message.content.trim().length > 0
    ))
    .slice(-24)
    .map((message) => ({
      role: message.type as 'user' | 'assistant',
      content: message.content,
    }))
}

function mergeUsage(messages: Message[]): TokenUsage {
  return messages.reduce<TokenUsage>((total, message) => {
    const usage = message.usage
    if (!usage) return total
    for (const [key, value] of Object.entries(usage)) {
      if (typeof value === 'number') {
        total[key] = (total[key] || 0) + value
      }
    }
    return total
  }, {})
}

function hasUsage(usage?: TokenUsage): boolean {
  return Boolean(usage && Object.values(usage).some((value) => typeof value === 'number' && value > 0))
}

function formatDuration(ms?: number): string {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
}

function formatToken(value?: number): string {
  if (typeof value !== 'number') return '-'
  return value.toLocaleString()
}

function stringifyJson(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function JsonDetails({
  label,
  value,
  defaultOpen = false,
}: {
  label: string
  value: unknown
  defaultOpen?: boolean
}) {
  if (value == null) return null
  const isObject = typeof value === 'object'
  return (
    <details className="json-details" open={defaultOpen || !isObject}>
      <summary>
        {label}
        {isObject && <span className="json-details__hint">展开 JSON</span>}
      </summary>
      <pre className="json-details__pre">{stringifyJson(value)}</pre>
    </details>
  )
}

function ToolCallCard({ call }: { call: ToolCallRecord }) {
  const statusLabel = call.status === 'running' ? 'running' : call.status === 'success' ? 'success' : 'error'
  return (
    <details className={`tool-call-card tool-call-card--${call.status}`}>
      <summary>
        <span className="tool-call-card__title">调用工具 {call.tool}</span>
        <span className="tool-call-card__status">{statusLabel}</span>
        {call.elapsedMs != null && (
          <span className="tool-call-card__duration">{formatDuration(call.elapsedMs)}</span>
        )}
      </summary>
      <div className="tool-call-card__body">
        <JsonDetails label="args" value={call.args} defaultOpen />
        <JsonDetails label="result" value={call.result} />
        <JsonDetails label="error" value={call.error} defaultOpen />
        {call.truncated && <div className="tool-call-card__note">结果已按后端预算截断</div>}
      </div>
    </details>
  )
}


function MessageTimeline({ items }: { items: MessageTimelineItem[] }) {
  if (items.length === 0) return null

  return (
    <div className="message-timeline">
      {items.map((item) => {
        if (item.kind === 'text') {
          if (!item.content) return null
          return (
            <div
              key={item.id}
              className="chat-bubble-text chat-markdown"
              dangerouslySetInnerHTML={{
                __html: renderMarkdown(item.content),
              }}
            />
          )
        }

        if (item.kind === 'tool_call' && item.toolCall) {
          return (
            <div className="tool-call-list" key={item.id}>
              <ToolCallCard call={item.toolCall} />
            </div>
          )
        }

        return null
      })}
    </div>
  )
}

function ProgressPill({ progress }: { progress?: AgentProgressEvent | null }) {
  if (!progress) return null
  const activity = progress.activity || 'running'
  const tool = typeof progress.tool === 'string' ? progress.tool : ''
  return (
    <div className="agent-progress-pill">
      <span className={`agent-progress-pill__dot agent-progress-pill__dot--${progress.status || 'running'}`} />
      <span>{activity}</span>
      {tool && <strong>{tool}</strong>}
      {typeof progress.elapsed_ms === 'number' && <span>{formatDuration(progress.elapsed_ms)}</span>}
    </div>
  )
}

export function ChatPanel() {
  const { state, dispatch } = useAppStore()
  const [input, setInput] = useState('')
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [sessionBusy, setSessionBusy] = useState(false)
  const [sessionError, setSessionError] = useState('')
  const [sessionsCollapsed, setSessionsCollapsed] = useState(false)
  const activeSessionIdRef = useRef<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  // 流式累积文本
  const [streamingText, setStreamingText] = useState('')
  const [streamingTools, setStreamingTools] = useState<ToolCallRecord[]>([])
  const [streamingTimeline, setStreamingTimeline] = useState<MessageTimelineItem[]>([])
  const [streamingProgress, setStreamingProgress] = useState<AgentProgressEvent | null>(null)

  const upsertSessionSummary = useCallback((session: ChatSession) => {
    const summary = summarizeSession(session)
    setSessions((prev) => [
      summary,
      ...prev.filter((item) => item.id !== summary.id),
    ])
  }, [])

  const openSession = useCallback(async (sessionId: string) => {
    setSessionBusy(true)
    setSessionError('')
    try {
      const res = await getChatSession(sessionId)
      if (res.status !== 'ok' || !res.data) {
        setSessionError(res.message || '加载会话失败')
        return
      }

      activeSessionIdRef.current = sessionId
      setActiveSessionId(sessionId)
      dispatch({ type: 'SET_MESSAGES', payload: res.data.messages || [] })
    } finally {
      setSessionBusy(false)
    }
  }, [dispatch])

  const createAndOpenSession = useCallback(async (): Promise<string | null> => {
    setSessionBusy(true)
    setSessionError('')
    try {
      const res = await createChatSession()
      if (res.status !== 'ok' || !res.data) {
        setSessionError(res.message || '创建会话失败')
        return null
      }

      upsertSessionSummary(res.data)
      activeSessionIdRef.current = res.data.id
      setActiveSessionId(res.data.id)
      dispatch({ type: 'SET_MESSAGES', payload: res.data.messages || [] })
      return res.data.id
    } finally {
      setSessionBusy(false)
    }
  }, [dispatch, upsertSessionSummary])

  const ensureActiveSession = useCallback(async (): Promise<string | null> => {
    if (activeSessionIdRef.current) return activeSessionIdRef.current
    return createAndOpenSession()
  }, [createAndOpenSession])

  const persistMessage = useCallback(async (sessionId: string, message: Message) => {
    const res = await addChatSessionMessage(sessionId, message)
    if (res.status === 'ok' && res.data) {
      upsertSessionSummary(res.data)
      return
    }
    setSessionError(res.message || '保存消息失败')
  }, [upsertSessionSummary])

  const handleDeleteSession = useCallback(async (
    sessionId: string,
    event: React.MouseEvent<HTMLButtonElement>
  ) => {
    event.stopPropagation()
    if (state.sending || sessionBusy) return
    if (!window.confirm('确认删除这个聊天分页吗？')) return

    const res = await deleteChatSession(sessionId)
    if (res.status !== 'ok') {
      setSessionError(res.message || '删除会话失败')
      return
    }

    const remaining = sessions.filter((item) => item.id !== sessionId)
    setSessions(remaining)

    if (activeSessionId !== sessionId) return
    if (remaining.length > 0) {
      await openSession(remaining[0].id)
    } else {
      await createAndOpenSession()
    }
  }, [
    activeSessionId,
    createAndOpenSession,
    openSession,
    sessionBusy,
    sessions,
    state.sending,
  ])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || state.sending) return

    const sessionId = await ensureActiveSession()
    if (!sessionId) {
      dispatch({
        type: 'ADD_MESSAGE',
        payload: {
          id: `error-${Date.now()}`,
          type: 'system',
          content: '没有可用的聊天分页，消息未发送',
          timestamp: new Date().toISOString(),
        },
      })
      return
    }

    setInput('')
    setStreamingText('')
    setStreamingTools([])
    setStreamingTimeline([])
    setStreamingProgress({ activity: 'planning', status: 'running', agent: 'assistant' })

    // 添加用户消息
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      type: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    dispatch({ type: 'ADD_MESSAGE', payload: userMsg })
    dispatch({ type: 'SET_SENDING', payload: true })
    await persistMessage(sessionId, userMsg)
    const contextMessages = buildContextMessages([...state.messages, userMsg])

    try {
      // 尝试流式端点
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          messages: contextMessages,
          session_id: sessionId,
        }),
      })

      if (!res.ok) {
        throw new Error(`服务器错误 (${res.status})`)
      }

      const reader = res.body?.getReader()
      if (!reader) throw new Error('浏览器不支持流式读取')

      const decoder = new TextDecoder()
      let buffer = ''
      let fullText = ''
      let finalContent = ''
      let memoriesUsed: number | undefined
      let responseUsage: TokenUsage | undefined
      let responseElapsedMs: number | undefined
      let responseToolCalls: ToolCallRecord[] = []
      let responseTimeline: MessageTimelineItem[] = []
      let streamOrder = 0
      const requestStartedAt = performance.now()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 按 SSE 格式拆分事件
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6)
          if (!jsonStr.trim()) continue

          try {
            const event = JSON.parse(jsonStr)

            if (event.type === 'agent_progress') {
              setStreamingProgress(event as AgentProgressEvent)
            } else if (event.type === 'thinking' && event.content) {
              fullText += event.content
              streamOrder += 1
              responseTimeline = appendTextTimelineItem(responseTimeline, event.content, streamOrder)
              setStreamingText(fullText)
              setStreamingTimeline(responseTimeline)
            } else if (event.type === 'tool_call') {
              const call: ToolCallRecord = {
                id: String(event.tool_call_id || `${event.tool || 'tool'}-${Date.now()}-${responseToolCalls.length}`),
                tool: String(event.tool || 'unknown'),
                status: 'running',
                args: event.args,
                startedAt: new Date().toISOString(),
                concurrent: Boolean(event.concurrent),
              }
              streamOrder += 1
              responseToolCalls = [...responseToolCalls, call]
              responseTimeline = upsertToolCallTimelineItem(responseTimeline, call, streamOrder)
              setStreamingTools(responseToolCalls)
              setStreamingTimeline(responseTimeline)
            } else if (event.type === 'tool_result') {
              const callId = String(event.tool_call_id || '')
              const resultStatus = event.status === 'error' ? 'error' : 'success'
              let resultPatch: Partial<ToolCallRecord> | null = null
              responseToolCalls = responseToolCalls.map((call) => {
                const matches = callId ? call.id === callId : call.tool === event.tool && call.status === 'running'
                if (!matches) return call
                const elapsedMs = typeof event.elapsed_ms === 'number'
                  ? event.elapsed_ms
                  : call.startedAt
                    ? Date.now() - new Date(call.startedAt).getTime()
                    : undefined
                const error = resultStatus === 'error'
                  ? (event.result && typeof event.result === 'object' && 'error' in event.result ? (event.result as Record<string, unknown>).error : event.result)
                  : undefined
                resultPatch = {
                  status: resultStatus,
                  result: event.result,
                  error,
                  elapsedMs,
                  finishedAt: new Date().toISOString(),
                  truncated: Boolean(event.truncated),
                }
                return {
                  ...call,
                  ...resultPatch,
                }
              })
              const fallbackCallId = callId || String(event.tool || `tool-result-${streamOrder + 1}`)
              if (!resultPatch) {
                resultPatch = {
                  id: fallbackCallId,
                  tool: String(event.tool || 'unknown'),
                  status: resultStatus,
                  result: event.result,
                  error: resultStatus === 'error' ? event.result : undefined,
                  elapsedMs: typeof event.elapsed_ms === 'number' ? event.elapsed_ms : undefined,
                  finishedAt: new Date().toISOString(),
                  truncated: Boolean(event.truncated),
                }
              }
              streamOrder += 1
              responseTimeline = updateToolResultTimelineItem(
                responseTimeline,
                callId || fallbackCallId,
                resultPatch,
                streamOrder,
              )
              setStreamingTools(responseToolCalls)
              setStreamingTimeline(responseTimeline)
            } else if (event.type === 'done') {
              if (event.usage) {
                responseUsage = event.usage
              }
              if (typeof event.elapsed_ms === 'number') {
                responseElapsedMs = event.elapsed_ms
              }
              if (event.content) {
                if (typeof event.content === 'string') {
                  finalContent = event.content
                } else if (event.content.response) {
                  finalContent = event.content.response
                  if (typeof event.content.memories_used === 'number') {
                    memoriesUsed = event.content.memories_used
                  }
                } else if (event.content.error) {
                  finalContent = `错误: ${event.content.error}`
                } else {
                  finalContent = JSON.stringify(event.content)
                }
              }
            }
          } catch {
            // 忽略解析错误
          }
        }
      }

      // 流结束，添加完整消息
      const responseText = finalContent || fullText || '(无响应)'
      if (responseTimeline.length === 0 && responseText) {
        streamOrder += 1
        responseTimeline = appendTextTimelineItem(responseTimeline, responseText, streamOrder)
      }
      const assistantMsg: Message = {
        id: `assistant-${Date.now()}`,
        type: 'assistant',
        content: responseText,
        timestamp: new Date().toISOString(),
        memoriesUsed,
        elapsedMs: responseElapsedMs ?? performance.now() - requestStartedAt,
        usage: responseUsage,
        toolCalls: responseToolCalls,
        timeline: responseTimeline,
        progress: { activity: 'completed', status: 'completed', agent: 'assistant' },
      }
      dispatch({ type: 'ADD_MESSAGE', payload: assistantMsg })
      await persistMessage(sessionId, assistantMsg)
      setStreamingText('')
      setStreamingTools([])
      setStreamingTimeline([])
      setStreamingProgress(null)
    } catch (err) {
      // fallback: 非流式
      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            messages: contextMessages,
            session_id: sessionId,
          }),
        })
        if (res.ok) {
          const data = await res.json()
          const responseText = data.response || data.content || JSON.stringify(data)
          const assistantMsg: Message = {
            id: `assistant-${Date.now()}`,
            type: 'assistant',
            content: responseText,
            timestamp: new Date().toISOString(),
            memoriesUsed: data.memories_used,
            elapsedMs: typeof data.elapsed_ms === 'number' ? data.elapsed_ms : undefined,
            usage: data.usage,
          }
          dispatch({ type: 'ADD_MESSAGE', payload: assistantMsg })
          await persistMessage(sessionId, assistantMsg)
          setStreamingText('')
          setStreamingTools([])
          setStreamingTimeline([])
          setStreamingProgress(null)
          return
        }
      } catch {
        // ignore fallback error
      }

      const errorMsg: Message = {
        id: `error-${Date.now()}`,
        type: 'system',
        content: `${err instanceof Error ? err.message : '发送失败'}`,
        timestamp: new Date().toISOString(),
      }
      dispatch({ type: 'ADD_MESSAGE', payload: errorMsg })
      await persistMessage(sessionId, errorMsg)
      setStreamingText('')
      setStreamingTools([])
      setStreamingTimeline([])
      setStreamingProgress(null)
    } finally {
      dispatch({ type: 'SET_SENDING', payload: false })
    }
  }, [
    dispatch,
    ensureActiveSession,
    input,
    persistMessage,
    state.messages,
    state.sending,
  ])

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId
  }, [activeSessionId])

  useEffect(() => {
    let cancelled = false

    async function initSessions() {
      setLoadingSessions(true)
      setSessionError('')
      try {
        const res = await listChatSessions()
        if (cancelled) return

        if (res.status !== 'ok' || !res.data) {
          setSessionError(res.message || '加载会话列表失败')
          return
        }

        setSessions(res.data)
        if (res.data.length > 0) {
          const firstSession = res.data[0]
          activeSessionIdRef.current = firstSession.id
          setActiveSessionId(firstSession.id)
          const sessionRes = await getChatSession(firstSession.id)
          if (cancelled) return
          if (sessionRes.status === 'ok' && sessionRes.data) {
            dispatch({
              type: 'SET_MESSAGES',
              payload: sessionRes.data.messages || [],
            })
          } else {
            setSessionError(sessionRes.message || '加载会话失败')
          }
        } else {
          const created = await createChatSession()
          if (cancelled) return
          if (created.status === 'ok' && created.data) {
            setSessions([summarizeSession(created.data)])
            activeSessionIdRef.current = created.data.id
            setActiveSessionId(created.data.id)
            dispatch({ type: 'SET_MESSAGES', payload: [] })
          } else {
            setSessionError(created.message || '创建会话失败')
          }
        }
      } finally {
        if (!cancelled) setLoadingSessions(false)
      }
    }

    initSessions()
    return () => {
      cancelled = true
    }
  }, [dispatch])

  // Auto-scroll
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [state.messages, streamingText, streamingTools, streamingTimeline, streamingProgress])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const sessionUsage = mergeUsage(state.messages)
  const sessionElapsedMs = state.messages.reduce(
    (total, message) => total + (typeof message.elapsedMs === 'number' ? message.elapsedMs : 0),
    0
  )
  const sessionMessageCount = state.messages.filter((msg) => msg.type !== 'system').length
  const sessionHasUsage = hasUsage(sessionUsage)

  return (
    <div className="chat-panel">
      <aside className={`chat-session-sidebar ${sessionsCollapsed ? 'chat-session-sidebar--collapsed' : ''}`}>
        <button
          className="chat-session-toggle"
          onClick={() => setSessionsCollapsed((value) => !value)}
          aria-label={sessionsCollapsed ? '展开聊天历史' : '收起聊天历史'}
          title={sessionsCollapsed ? '展开聊天历史' : '收起聊天历史'}
        >
          <span className="chat-session-toggle-glyph">
            {sessionsCollapsed ? '›' : '‹'}
          </span>
          {sessionsCollapsed && sessions.length > 0 && (
            <span className="chat-session-toggle-badge">
              {sessions.length > 99 ? '99+' : sessions.length}
            </span>
          )}
        </button>
        <div className="chat-session-header">
          <div className="chat-session-heading">
            <span className="chat-session-kicker">Conversations</span>
            <h3>会话</h3>
          </div>
          <div className="chat-session-actions">
            <button
              className="chat-session-new"
              onClick={createAndOpenSession}
              disabled={state.sending || sessionBusy || sessionsCollapsed}
              title="新建会话"
            >
              <span aria-hidden="true">+</span>
              <span>新建</span>
            </button>
          </div>
        </div>

        {!sessionsCollapsed && sessionError && (
          <div className="chat-session-error">{sessionError}</div>
        )}

        {!sessionsCollapsed && (
          <div className="chat-session-list">
            {loadingSessions ? (
              <div className="chat-session-loading">加载历史中...</div>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  className={`chat-session-item ${session.id === activeSessionId ? 'chat-session-item--active' : ''}`}
                >
                  <button
                    className="chat-session-open"
                    onClick={() => openSession(session.id)}
                    disabled={state.sending || sessionBusy}
                  >
                    <span className="chat-session-title">{session.title}</span>
                    <span className="chat-session-preview">
                      {session.last_message || '空会话'}
                    </span>
                    <span className="chat-session-meta">
                      {formatSessionTime(session.updated_at)} · {session.message_count} 条
                    </span>
                  </button>
                  <button
                    className="chat-session-delete"
                    onClick={(event) => handleDeleteSession(session.id, event)}
                    disabled={state.sending || sessionBusy}
                    aria-label="删除会话"
                  >
                    ×
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </aside>

      <section className="chat-main">
        <div className="chat-metrics-bar" aria-label="当前对话指标">
          <span className="chat-metric">
            Msg <strong>{sessionMessageCount}</strong>
          </span>
          <span className="chat-metric">
            Tok <strong>{formatToken(sessionUsage.total_tokens)}</strong>
          </span>
          <span className="chat-metric chat-metric--tokens">
            ↑ {formatToken(sessionUsage.input_tokens)} / ↓ {formatToken(sessionUsage.output_tokens)}
          </span>
          <span className="chat-metric">
            {sessionElapsedMs > 0 ? formatDuration(sessionElapsedMs) : '-'}
          </span>
          {state.sending && <span className="chat-metrics-live">生成中</span>}
          {!sessionHasUsage && <span className="chat-metrics-empty">待更新</span>}
        </div>
        {/* Messages Area */}
        <div className="chat-messages" ref={listRef}>
          {state.messages.length === 0 && !streamingText ? (
            <div className="chat-empty">
              <div className="chat-empty-icon">
                <svg viewBox="0 0 24 24">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <h3>多智能体协作系统</h3>
              <p>{sessionBusy ? '正在加载聊天分页...' : '发送消息开始与 AI 智能体交互'}</p>
              {!state.connected && (
                <p style={{ color: 'var(--color-warning)', fontSize: '13px', marginTop: '8px' }}>
                  尚未连接到后端服务
                </p>
              )}
            </div>
          ) : (
            state.messages.map((msg) => (
              <div
                key={msg.id}
                className={`chat-row chat-row-${msg.type}`}
              >
                {msg.type === 'assistant' && (
                  <div className="chat-avatar">A</div>
                )}
                {msg.type === 'system' ? (
                  <div className="chat-system-msg">
                    {msg.content}
                  </div>
                ) : (
                  <div className={`chat-bubble chat-bubble-${msg.type}`}>
                    <MessageTimeline items={getMessageTimeline(msg)} />
                    {msg.memoriesUsed != null && msg.memoriesUsed > 0 && (
                      <div className="chat-memory-indicator">
                        使用了 {msg.memoriesUsed} 条记忆
                      </div>
                    )}
                    <div className="chat-message-meta">
                      <span>{new Date(msg.timestamp).toLocaleTimeString()}</span>
                      {msg.elapsedMs != null && <span>耗时 {formatDuration(msg.elapsedMs)}</span>}
                      {hasUsage(msg.usage) ? (
                        <span>
                          Token ↑ {formatToken(msg.usage?.input_tokens)}
                          {' / '}↓ {formatToken(msg.usage?.output_tokens)}
                          {' / '}Σ {formatToken(msg.usage?.total_tokens)}
                        </span>
                      ) : msg.type === 'assistant' ? (
                        <span className="chat-meta-warning">Token 未返回</span>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            ))
          )}

          {/* 流式输出区域 */}
          {state.sending && (streamingText || streamingTools.length > 0 || streamingProgress) && (
            <div className="chat-row chat-row-assistant">
              <div className="chat-avatar">A</div>
              <div className="chat-bubble chat-bubble-assistant">
                <ProgressPill progress={streamingProgress} />
                <MessageTimeline items={streamingTimeline} />
                <span className="streaming-cursor" />
              </div>
            </div>
          )}

          {/* 等待中指示器（还没收到任何流事件） */}
          {state.sending && !streamingText && streamingTools.length === 0 && !streamingProgress && (
            <div className="chat-row chat-row-assistant">
              <div className="chat-avatar">A</div>
              <div className="chat-bubble chat-bubble-assistant">
                <div className="chat-typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="chat-input-area">
          <div className="chat-input-wrapper">
            <textarea
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={state.connected ? '输入消息... (Enter 发送, Shift+Enter 换行)' : '未连接到后端，但仍可发送消息...'}
              rows={1}
              disabled={state.sending || sessionBusy}
            />
            <button
              className="chat-send-btn"
              onClick={handleSend}
              disabled={!input.trim() || state.sending || sessionBusy}
            >
              {state.sending ? (
                <span className="send-spinner" />
              ) : (
                '发送'
              )}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
