import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type {
  AgentInfo,
  Attachment,
  ChatMessage,
  ChatSession,
  ChatSessionSummary,
} from '../types'
import { Select } from './Select'
import { agentMetaFromList } from './agentBadge'
import './ChatPanel.css'

const SESSIONS_COLLAPSED_KEY = 'chat.sessionsCollapsed'

function MessageBody({ content }: { content: string }) {
  return (
    <div className="chat-msg__body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

function formatTime(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function formatDate(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const now = new Date()
  if (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  ) {
    return `今天 ${date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })}`
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function makeMessageId() {
  return `msg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function toAgentHistory(messages: ChatMessage[], nextMessage: ChatMessage) {
  const history = [...messages, nextMessage].flatMap((message) => {
    if (message.type !== 'user' && message.type !== 'assistant') return []
    return [{ role: message.type, content: message.content }]
  })
  return history.slice(-30)
}

function extractAssistantText(payload: any): string {
  if (payload == null) return ''
  if (typeof payload === 'string') return payload
  if (typeof payload !== 'object') return String(payload)
  for (const key of [
    'content',
    'text',
    'response',
    'message',
    'output',
    'reply',
    'answer',
  ]) {
    const value = (payload as Record<string, any>)[key]
    if (typeof value === 'string' && value.trim()) return value
    if (value && typeof value === 'object') {
      const nested = extractAssistantText(value)
      if (nested) return nested
    }
  }
  if (Array.isArray((payload as any).messages)) {
    const last = (payload as any).messages[(payload as any).messages.length - 1]
    if (last) return extractAssistantText(last)
  }
  return JSON.stringify(payload)
}

export function ChatPanel() {
  const { state } = useAppStore()
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null)
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [agentName, setAgentName] = useState<string>('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  // B1 — 待发送附件草稿。上传完成的文件先存这里，handleSend 时 attachments=ids。
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<number>(0)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [sessionsCollapsed, setSessionsCollapsed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(SESSIONS_COLLAPSED_KEY) === '1'
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(SESSIONS_COLLAPSED_KEY, sessionsCollapsed ? '1' : '0')
  }, [sessionsCollapsed])

  const transcriptRef = useRef<HTMLDivElement | null>(null)

  // Load agent list
  useEffect(() => {
    api.listAgents().then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) {
        const list = res.data
        setAgents(list)
        const assistant = list.find((agent) => agent.name === 'assistant')
        setAgentName((current) => current || assistant?.name || list[0]?.name || '')
      }
    })
  }, [])

  const loadSessions = useCallback(async (preferredId?: string) => {
    const res = await api.listChatSessions()
    if (res.status !== 'ok' || !Array.isArray(res.data)) {
      setError(res.message || '加载会话失败')
      return
    }
    const sorted = [...res.data].sort((a, b) =>
      (b.updated_at || '').localeCompare(a.updated_at || '')
    )
    setSessions(sorted)
    setSelectedSessionId((current) => {
      if (preferredId && sorted.some((session) => session.id === preferredId))
        return preferredId
      if (current && sorted.some((session) => session.id === current)) return current
      return sorted[0]?.id || null
    })
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // Load active session messages
  useEffect(() => {
    if (!selectedSessionId) {
      setActiveSession(null)
      return
    }
    let cancelled = false
    api.getChatSession(selectedSessionId).then((res) => {
      if (cancelled) return
      if (res.status === 'ok' && res.data) {
        setActiveSession(res.data)
      } else {
        setError(res.message || '加载会话失败')
      }
    })
    return () => {
      cancelled = true
    }
  }, [selectedSessionId])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [activeSession?.messages?.length])

  const handleNewSession = async () => {
    const res = await api.createChatSession({
      workspace_id: state.selectedWorkspace?.id || undefined,
    })
    if (res.status === 'ok' && res.data) {
      await loadSessions(res.data.id)
      setActiveSession(res.data)
    } else {
      setError(res.message || '创建会话失败')
    }
  }

  const handleDeleteSession = async (sessionId: string) => {
    if (!window.confirm('确认删除此会话？历史消息将一并清除。')) return
    const res = await api.deleteChatSession(sessionId)
    if (res.status === 'ok') {
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(null)
        setActiveSession(null)
      }
      await loadSessions()
    } else {
      setError(res.message || '删除失败')
    }
  }

  const handleStartRename = () => {
    if (!activeSession) return
    setRenameValue(activeSession.title || '')
    setRenaming(true)
  }

  const handleSubmitRename = async () => {
    if (!activeSession) return
    const trimmed = renameValue.trim()
    if (!trimmed || trimmed === activeSession.title) {
      setRenaming(false)
      return
    }
    const res = await api.updateChatSession(activeSession.id, { title: trimmed })
    if (res.status === 'ok' && res.data) {
      setActiveSession(res.data)
      await loadSessions(activeSession.id)
    } else {
      setError(res.message || '重命名失败')
    }
    setRenaming(false)
  }

  const handleSend = async () => {
    const value = input.trim()
    const attachmentIds = pendingAttachments.map((a) => a.id)
    if (!agentName) return
    if (!value && attachmentIds.length === 0) return

    let session = activeSession
    if (!session) {
      const created = await api.createChatSession({
        workspace_id: state.selectedWorkspace?.id || undefined,
      })
      if (created.status !== 'ok' || !created.data) {
        setError(created.message || '创建会话失败')
        return
      }
      session = created.data
      setActiveSession(session)
      setSelectedSessionId(session.id)
      await loadSessions(session.id)
    }

    const sessionId = session.id
    const userMessage: ChatMessage = {
      id: makeMessageId(),
      type: 'user',
      content: value,
      timestamp: new Date().toISOString(),
      attachments: attachmentIds.length > 0 ? attachmentIds : undefined,
    }
    setActiveSession((prev) =>
      prev ? { ...prev, messages: [...prev.messages, userMessage] } : prev
    )
    setInput('')
    setPendingAttachments([])
    setSending(true)
    setError('')

    // Persist user message
    await api.addChatSessionMessage(sessionId, {
      id: userMessage.id,
      type: 'user',
      content: userMessage.content,
      timestamp: userMessage.timestamp,
      attachments: userMessage.attachments,
    })

    const startedAt = Date.now()
    const result = await api.invokeAgent(agentName, value, {
      session_id: sessionId,
      workspace_id: session.workspace_id || state.selectedWorkspace?.id || undefined,
      messages: toAgentHistory(session.messages || [], userMessage),
    })
    const elapsedMs = Date.now() - startedAt

    if (result.status === 'ok') {
      const text = extractAssistantText(result.data) || '（无回复）'
      const memoriesUsed = (() => {
        const data = result.data as any
        if (data && typeof data === 'object') {
          const ctx = data.memories_used ?? data.memory_context ?? data.memoriesUsed
          if (typeof ctx === 'number') return ctx
          if (Array.isArray(data.memories)) return data.memories.length
        }
        return undefined
      })()
      const usage = (() => {
        const data = result.data as any
        if (data && typeof data === 'object' && data.usage && typeof data.usage === 'object') {
          return data.usage as Record<string, number>
        }
        return undefined
      })()
      const assistantMsg: ChatMessage = {
        id: makeMessageId(),
        type: 'assistant',
        content: text,
        timestamp: new Date().toISOString(),
        memoriesUsed,
        elapsedMs,
        usage,
        agent_name: agentName,
      }
      setActiveSession((prev) =>
        prev ? { ...prev, messages: [...prev.messages, assistantMsg] } : prev
      )
      await api.addChatSessionMessage(sessionId, {
        id: assistantMsg.id,
        type: 'assistant',
        content: assistantMsg.content,
        timestamp: assistantMsg.timestamp,
        memoriesUsed,
        elapsedMs,
        usage,
        agent_name: assistantMsg.agent_name,
      })
    } else {
      const errorMsg: ChatMessage = {
        id: makeMessageId(),
        type: 'system',
        content: result.message || '调用失败',
        timestamp: new Date().toISOString(),
        error: result.message || 'invoke_failed',
      }
      setActiveSession((prev) =>
        prev ? { ...prev, messages: [...prev.messages, errorMsg] } : prev
      )
      await api.addChatSessionMessage(sessionId, {
        id: errorMsg.id,
        type: 'system',
        content: errorMsg.content,
        timestamp: errorMsg.timestamp,
        error: errorMsg.error,
      })
      setError(result.message || '调用失败')
    }

    setSending(false)
    await loadSessions(sessionId)
  }

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !sending) {
      event.preventDefault()
      handleSend()
    }
  }

  // ─── B1 附件上传：paste / drop / 文件选择器三入口共用 ──────────────────
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const composerRef = useRef<HTMLDivElement | null>(null)

  const handleUpload = useCallback(
    async (files: File[]) => {
      if (!files.length) return
      // 用当前会话 id 当 scope；没会话用 draft，让消息发出后再追溯关联也无所谓——
      // attachments 是 message 上的引用，scope 仅用于目录归类。
      const scope = activeSession ? `chat_session:${activeSession.id}` : 'chat_session:draft'
      setUploadingFiles((n) => n + files.length)
      try {
        for (const file of files) {
          const res = await api.uploadAttachment(file, scope)
          if (res.status === 'ok' && res.data) {
            setPendingAttachments((prev) => [...prev, res.data as Attachment])
          } else {
            setError(res.message || `上传 ${file.name} 失败`)
          }
        }
      } finally {
        setUploadingFiles((n) => Math.max(0, n - files.length))
      }
    },
    [activeSession]
  )

  const handleRemovePending = useCallback((id: string) => {
    setPendingAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const onPaste = useCallback(
    (event: React.ClipboardEvent<HTMLDivElement>) => {
      const items = Array.from(event.clipboardData?.items || [])
      const files = items
        .filter((i) => i.kind === 'file')
        .map((i) => i.getAsFile())
        .filter((f): f is File => f != null)
      if (files.length > 0) {
        event.preventDefault()
        handleUpload(files)
      }
    },
    [handleUpload]
  )

  const onDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (event.dataTransfer?.types?.includes('Files')) {
      event.preventDefault()
    }
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      const files = Array.from(event.dataTransfer?.files || [])
      if (files.length > 0) {
        event.preventDefault()
        handleUpload(files)
      }
    },
    [handleUpload]
  )

  const onFilePicked = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files || [])
      event.target.value = ''
      if (files.length > 0) await handleUpload(files)
    },
    [handleUpload]
  )

  const sessionWorkspaceName = useMemo(() => {
    if (!activeSession?.workspace_id) return ''
    const workspace = state.workspaces.find(
      (item) => item.id === activeSession.workspace_id
    )
    return workspace?.name || activeSession.workspace_id
  }, [activeSession, state.workspaces])

  const agentMeta = useMemo(() => agentMetaFromList(agents), [agents])

  return (
    <div className="page chat-page">
      <div className="page__header">
        <div>
          <h1 className="page__title">对话</h1>
          <div className="page__subtitle">
            按会话维度持久化历史消息。每条消息会调用所选智能体并记录回复。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" className="btn-primary" onClick={handleNewSession}>
            新建会话
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error">
          <span style={{ flex: 1 }}>{error}</span>
          <button className="btn-xs" onClick={() => setError('')}>
            关闭
          </button>
        </div>
      )}

      <div className={`chat-shell ${sessionsCollapsed ? 'chat-shell--collapsed' : ''}`}>
        <aside className="chat-sessions">
          {sessionsCollapsed ? (
            <button
              type="button"
              className="chat-sessions__toggle chat-sessions__toggle--rail"
              onClick={() => setSessionsCollapsed(false)}
              title="展开会话列表"
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>
          ) : (
            <>
              <div className="chat-sessions__header">
                <span style={{ fontWeight: 600 }}>会话列表</span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span className="text-muted">{sessions.length}</span>
                  <button
                    type="button"
                    className="chat-sessions__toggle"
                    onClick={() => setSessionsCollapsed(true)}
                    title="收起会话列表"
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="15 18 9 12 15 6" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="chat-sessions__list">
            {sessions.length === 0 ? (
              <div className="empty-state" style={{ padding: 18 }}>
                <strong>还没有会话</strong>
                <span>点击右上角「新建会话」开始。</span>
              </div>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  className={`chat-session-row ${
                    selectedSessionId === session.id
                      ? 'chat-session-row--active'
                      : ''
                  }`}
                  onClick={() => setSelectedSessionId(session.id)}
                >
                  <div className="chat-session-row__title">
                    {session.title || '未命名会话'}
                  </div>
                  <div className="chat-session-row__preview">
                    {session.last_message_preview ||
                      session.last_message ||
                      '— 暂无消息 —'}
                  </div>
                  <div className="chat-session-row__meta">
                    <span>{formatDate(session.updated_at)}</span>
                    {typeof session.message_count === 'number' && (
                      <span>{session.message_count} 条</span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="chat-session-row__delete"
                    onClick={(event) => {
                      event.stopPropagation()
                      handleDeleteSession(session.id)
                    }}
                    title="删除会话"
                  >
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>
            </>
          )}
        </aside>

        <section className="chat-main">
          <header className="chat-main__header">
            <div className="chat-main__title-row">
              {renaming ? (
                <input
                  autoFocus
                  type="text"
                  value={renameValue}
                  onChange={(event) => setRenameValue(event.target.value)}
                  onBlur={handleSubmitRename}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') handleSubmitRename()
                    if (event.key === 'Escape') setRenaming(false)
                  }}
                  className="chat-main__title-input"
                />
              ) : (
                <h2
                  className="chat-main__title"
                  onDoubleClick={handleStartRename}
                  title="双击重命名"
                >
                  {activeSession?.title || '未命名会话'}
                </h2>
              )}
              {activeSession && (
                <button
                  type="button"
                  className="btn-xs"
                  onClick={handleStartRename}
                >
                  重命名
                </button>
              )}
            </div>
            <div className="chat-main__meta">
              {activeSession && (
                <>
                  <span>会话 ID {activeSession.id.slice(0, 8)}</span>
                  {sessionWorkspaceName && (
                    <span>工作区 {sessionWorkspaceName}</span>
                  )}
                  <span>共 {activeSession.messages?.length || 0} 条消息</span>
                </>
              )}
            </div>
          </header>

          <div className="chat-main__transcript" ref={transcriptRef}>
            {!activeSession || activeSession.messages.length === 0 ? (
              <div className="empty-state" style={{ padding: 60 }}>
                <strong>开始对话</strong>
                <span>
                  在下方输入框输入消息并按 Enter 发送。<br />
                  Shift+Enter 换行。
                </span>
              </div>
            ) : (
              activeSession.messages.map((message) => (
                <div
                  key={message.id}
                  className={`chat-msg chat-msg--${message.type}`}
                >
                  <div className="chat-msg__head">
                    <span className="chat-msg__role">
                      {message.type === 'user'
                        ? '用户'
                        : message.type === 'assistant'
                        ? message.agent_name || 'assistant'
                        : '系统'}
                    </span>
                    {message.type === 'assistant' &&
                      (() => {
                        const name = message.agent_name || 'assistant'
                        const model = agentMeta[name]?.model
                        return model ? (
                          <small
                            className="agent-model-badge"
                            title={`LLM 模型：${model}`}
                          >
                            {model}
                          </small>
                        ) : null
                      })()}
                    <span className="chat-msg__time">
                      {formatTime(message.timestamp)}
                    </span>
                    {message.elapsedMs != null && (
                      <span className="chat-msg__stat">
                        {(message.elapsedMs / 1000).toFixed(1)}s
                      </span>
                    )}
                    {message.memoriesUsed != null && message.memoriesUsed > 0 && (
                      <span className="chat-msg__stat">
                        记忆 {message.memoriesUsed}
                      </span>
                    )}
                    {message.usage?.total_tokens != null && (
                      <span className="chat-msg__stat">
                        {message.usage.total_tokens} tokens
                      </span>
                    )}
                  </div>
                  <MessageBody content={message.content} />
                </div>
              ))
            )}
            {sending && (
              <div className="chat-msg chat-msg--assistant chat-msg--loading">
                <div className="chat-msg__head">
                  <span className="chat-msg__role">{agentName}</span>
                  {agentMeta[agentName]?.model && (
                    <small
                      className="agent-model-badge"
                      title={`LLM 模型：${agentMeta[agentName]?.model}`}
                    >
                      {agentMeta[agentName]?.model}
                    </small>
                  )}
                  <span className="chat-msg__time">…</span>
                </div>
                <div className="chat-msg__body">
                  <span className="chat-typing">
                    <span />
                    <span />
                    <span />
                  </span>
                </div>
              </div>
            )}
          </div>

          <div
            className="chat-main__composer"
            ref={composerRef}
            onPaste={onPaste}
            onDragOver={onDragOver}
            onDrop={onDrop}
          >
            <div className="chat-main__composer-bar">
              <div className="chat-main__composer-field">
                <span className="chat-main__composer-label">智能体</span>
                <Select
                  size="sm"
                  fullWidth={false}
                  value={agentName}
                  onChange={setAgentName}
                  placeholder={agents.length ? '选择智能体' : '未注册智能体'}
                  disabled={agents.length === 0}
                  options={agents.map((agent) => ({
                    value: agent.name,
                    label: agent.name,
                    description: agent.description || '无描述',
                  }))}
                />
              </div>
              {state.selectedWorkspace?.id && (
                <span className="chat-main__composer-meta">
                  当前工作区：{state.selectedWorkspace.name}
                </span>
              )}
            </div>
            {(pendingAttachments.length > 0 || uploadingFiles > 0) && (
              <div className="chat-main__composer-attachments">
                {pendingAttachments.map((att) => (
                  <span
                    key={att.id}
                    className="chat-main__composer-chip"
                    title={`${att.filename} · ${att.mime_type}`}
                  >
                    {att.mime_type.startsWith('image/') ? (
                      <img
                        src={api.attachmentContentUrl(att.id)}
                        alt={att.filename}
                        className="chat-main__composer-chip-thumb"
                      />
                    ) : (
                      <span className="chat-main__composer-chip-icon">📎</span>
                    )}
                    <span className="chat-main__composer-chip-name">{att.filename}</span>
                    <button
                      type="button"
                      className="chat-main__composer-chip-remove"
                      onClick={() => handleRemovePending(att.id)}
                      aria-label="移除附件"
                    >
                      ✕
                    </button>
                  </span>
                ))}
                {uploadingFiles > 0 && (
                  <span className="chat-main__composer-chip chat-main__composer-chip--uploading">
                    上传中… ({uploadingFiles})
                  </span>
                )}
              </div>
            )}
            <textarea
              className="chat-main__composer-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder={
                agents.length
                  ? '输入消息，Enter 发送，Shift+Enter 换行（支持粘贴/拖拽附件）'
                  : '请先在「智能体」页注册一个智能体'
              }
              disabled={agents.length === 0 || sending}
              rows={3}
            />
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={onFilePicked}
            />
            <div className="chat-main__composer-actions">
              <button
                type="button"
                className="btn-secondary chat-main__composer-attach-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={sending}
                title="添加附件（也可粘贴/拖拽）"
              >
                📎 附件
              </button>
              <span className="text-muted" style={{ fontSize: 11 }}>
                调用 /api/agents/{agentName || '?'}/invoke
              </span>
              <button
                type="button"
                className="btn-primary"
                onClick={handleSend}
                disabled={
                  (!input.trim() && pendingAttachments.length === 0) ||
                  sending ||
                  !agentName ||
                  uploadingFiles > 0
                }
              >
                {sending ? '发送中…' : '发送'}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
