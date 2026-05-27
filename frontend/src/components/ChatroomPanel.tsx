import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { Select } from './Select'
import { getSettingLabel } from './chatroomSettingsLabels'
import { senderToDisplay, agentMetaFromList, type AgentMetaMap } from './agentBadge'
import type {
  AgentInfo,
  Chatroom,
  ChatroomCreatePayload,
  ChatroomMessage,
  ChatroomMessageStatus,
  ChatroomSettings,
  ChatroomSummary,
  ChatroomToolCallRecord,
  ChatroomUpdatePayload,
  ManagedWorkspace,
  WSEvent,
} from '../types'
import './ChatroomPanel.css'

// ─── 工具函数 ────────────────────────────────────────────

const AGENT_HASH_COLORS = [
  '#b85f3f',
  '#3d7daa',
  '#2f7a3a',
  '#a64ca6',
  '#b87828',
  '#3a7d7d',
]

function hashColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0
  }
  const idx = Math.abs(hash) % AGENT_HASH_COLORS.length
  return AGENT_HASH_COLORS[idx]
}

function senderIsAgent(sender: string): boolean {
  return sender.startsWith('agent:')
}

function avatarLabel(name: string): string {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  return trimmed.slice(0, 1).toUpperCase()
}

function formatTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function formatDate(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const now = new Date()
  if (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  ) {
    return `今天 ${date.toLocaleTimeString('zh-CN', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    })}`
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

const MENTION_REGEX = /@([A-Za-z0-9_\-一-鿿㐀-䶿]+)/g

function MentionText({ text }: { text: string }) {
  // 切分文本为「普通文本片段 + mention chip」交错列表
  const segments: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  const re = new RegExp(MENTION_REGEX.source, 'g')
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push(text.slice(lastIndex, match.index))
    }
    segments.push(
      <span
        className="chatroom-mention"
        key={`m-${match.index}`}
        style={{ color: hashColor(match[1]) }}
      >
        @{match[1]}
      </span>
    )
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    segments.push(text.slice(lastIndex))
  }
  return <>{segments}</>
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <div className="chatroom-msg__body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
          // text 节点替换：让 @AgentName 高亮
          p: ({ children }: { children?: ReactNode }) => (
            <p>{wrapMentionsInChildren(children)}</p>
          ),
          li: ({ children }: { children?: ReactNode }) => (
            <li>{wrapMentionsInChildren(children)}</li>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

function wrapMentionsInChildren(children: ReactNode): ReactNode {
  if (typeof children === 'string') {
    return <MentionText text={children} />
  }
  if (Array.isArray(children)) {
    return children.map((child, i) =>
      typeof child === 'string' ? (
        <MentionText key={i} text={child} />
      ) : (
        <span key={i}>{child}</span>
      )
    )
  }
  return children
}

function statusLabel(status: ChatroomMessageStatus): string {
  switch (status) {
    case 'pending':
      return '等待中'
    case 'streaming':
      return '思考中'
    case 'failed':
      return '失败'
    case 'done':
    default:
      return ''
  }
}

const DEFAULT_SETTINGS: ChatroomSettings = {
  auto_host: false,
  host_agent: 'planner',
  recent_n: 30,
  summary_threshold_m: 20,
  max_relay_depth: 3,
  max_members: 20,
  allow_agent_invite: true,
}

function mergeMessage(
  prev: ChatroomMessage[],
  incoming: ChatroomMessage
): ChatroomMessage[] {
  const idx = prev.findIndex((m) => m.id === incoming.id)
  if (idx === -1) {
    return [...prev, incoming]
  }
  const merged: ChatroomMessage = {
    ...prev[idx],
    ...incoming,
    // 保留前端运行时附加字段
    thinking_buffer:
      incoming.thinking_buffer ?? prev[idx].thinking_buffer ?? '',
    tool_calls: incoming.tool_calls ?? prev[idx].tool_calls ?? [],
  }
  const next = [...prev]
  next[idx] = merged
  return next
}

// ─── 主组件 ───────────────────────────────────────────────

export function ChatroomPanel() {
  const { state } = useAppStore()
  const [rooms, setRooms] = useState<ChatroomSummary[]>([])
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null)
  const [activeRoom, setActiveRoom] = useState<Chatroom | null>(null)
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [error, setError] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showBannerDetails, setShowBannerDetails] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [mentionPicker, setMentionPicker] = useState<{
    visible: boolean
    query: string
    position: number
  }>({ visible: false, query: '', position: 0 })

  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const subscribedRoomIdRef = useRef<string | null>(null)
  // 保存当前活跃 room 的 id，便于 onMessage 闭包内访问最新值
  const activeRoomIdRef = useRef<string | null>(null)
  activeRoomIdRef.current = activeRoom?.id ?? null

  // ─── 数据加载 ───────────────────────────────────────────
  const loadRooms = useCallback(
    async (preferredId?: string) => {
      const res = await api.listChatrooms()
      if (res.status !== 'ok' || !Array.isArray(res.data)) {
        setError(res.message || '加载聊天室失败')
        return
      }
      const sorted = [...res.data].sort((a, b) =>
        (b.last_message_at || b.updated_at || '').localeCompare(
          a.last_message_at || a.updated_at || ''
        )
      )
      setRooms(sorted)
      setSelectedRoomId((current) => {
        if (preferredId && sorted.some((r) => r.id === preferredId))
          return preferredId
        if (current && sorted.some((r) => r.id === current)) return current
        return sorted[0]?.id || null
      })
    },
    []
  )

  const loadActiveRoom = useCallback(async (roomId: string) => {
    const res = await api.getChatroom(roomId)
    if (res.status === 'ok' && res.data) {
      setActiveRoom(res.data)
    } else {
      setError(res.message || '加载房间详情失败')
    }
  }, [])

  useEffect(() => {
    loadRooms()
  }, [loadRooms])

  useEffect(() => {
    api.listAgents().then((res) => {
      if (res.status === 'ok' && Array.isArray(res.data)) {
        setAgents(res.data)
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedRoomId) {
      setActiveRoom(null)
      return
    }
    let cancelled = false
    api.getChatroom(selectedRoomId).then((res) => {
      if (cancelled) return
      if (res.status === 'ok' && res.data) {
        setActiveRoom(res.data)
      } else {
        setError(res.message || '加载房间详情失败')
      }
    })
    return () => {
      cancelled = true
    }
  }, [selectedRoomId])

  // ─── WebSocket（独立连接，不影响全局 ws）─────────────────
  const wsUrl = useMemo(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws`
  }, [])

  const handleWSMessage = useCallback((raw: unknown) => {
    const event = raw as WSEvent
    const eventType = event.event_type || event.type
    const roomId = activeRoomIdRef.current
    if (!roomId) return
    const data = (event.data || {}) as Record<string, any>
    if (data.room_id && data.room_id !== roomId) {
      return
    }

    switch (eventType) {
      case 'chatroom_message_added':
      case 'chatroom_message_started':
      case 'chatroom_message_done': {
        const message: ChatroomMessage | undefined = data.message
        if (!message) return
        setActiveRoom((prev) => {
          if (!prev || prev.id !== roomId) return prev
          return { ...prev, messages: mergeMessage(prev.messages, message) }
        })
        break
      }
      case 'chatroom_agent_thinking': {
        const messageId: string | undefined = data.message_id
        const delta: string = data.delta || ''
        if (!messageId) return
        setActiveRoom((prev) => {
          if (!prev || prev.id !== roomId) return prev
          return {
            ...prev,
            messages: prev.messages.map((m) =>
              m.id === messageId
                ? {
                    ...m,
                    thinking_buffer: (m.thinking_buffer || '') + delta,
                    status:
                      m.status === 'pending' ? 'streaming' : m.status,
                  }
                : m
            ),
          }
        })
        break
      }
      case 'chatroom_tool_call': {
        const messageId: string | undefined = data.message_id
        if (!messageId) return
        const toolCall: ChatroomToolCallRecord = {
          tool_call_id: String(data.tool_call_id || `${data.tool_name}:${Date.now()}`),
          tool_name: String(data.tool_name || ''),
          args: data.args,
          status: 'running',
        }
        setActiveRoom((prev) => {
          if (!prev || prev.id !== roomId) return prev
          return {
            ...prev,
            messages: prev.messages.map((m) => {
              if (m.id !== messageId) return m
              const existing = m.tool_calls || []
              if (existing.some((c) => c.tool_call_id === toolCall.tool_call_id)) {
                return m
              }
              return { ...m, tool_calls: [...existing, toolCall] }
            }),
          }
        })
        break
      }
      case 'chatroom_tool_result': {
        const messageId: string | undefined = data.message_id
        if (!messageId) return
        const callId = String(data.tool_call_id || '')
        setActiveRoom((prev) => {
          if (!prev || prev.id !== roomId) return prev
          return {
            ...prev,
            messages: prev.messages.map((m) => {
              if (m.id !== messageId) return m
              const calls = m.tool_calls || []
              return {
                ...m,
                tool_calls: calls.map((c) =>
                  c.tool_call_id === callId
                    ? {
                        ...c,
                        result_preview: data.result_preview,
                        elapsed_ms: data.elapsed_ms ?? null,
                        status: data.status || 'success',
                      }
                    : c
                ),
              }
            }),
          }
        })
        break
      }
      case 'chatroom_message_failed': {
        const messageId: string | undefined =
          data.message_id || (data.message && data.message.id)
        if (data.message) {
          setActiveRoom((prev) => {
            if (!prev || prev.id !== roomId) return prev
            return { ...prev, messages: mergeMessage(prev.messages, data.message) }
          })
        } else if (messageId) {
          setActiveRoom((prev) => {
            if (!prev || prev.id !== roomId) return prev
            return {
              ...prev,
              messages: prev.messages.map((m) =>
                m.id === messageId
                  ? {
                      ...m,
                      status: 'failed',
                      meta: { ...m.meta, error: data.error },
                    }
                  : m
              ),
            }
          })
        }
        break
      }
      case 'chatroom_summary_updated': {
        setActiveRoom((prev) => {
          if (!prev || prev.id !== roomId) return prev
          return {
            ...prev,
            summary: data.summary || prev.summary,
            summary_until_msg_id:
              data.summary_until_msg_id || prev.summary_until_msg_id,
          }
        })
        break
      }
      case 'chatroom_goal_updated': {
        // 后端目前未发出此事件（Phase 4 工具会发）；先全量刷新作为兜底
        loadActiveRoom(roomId)
        break
      }
      case 'chatroom_member_added':
      case 'chatroom_member_removed': {
        loadActiveRoom(roomId)
        loadRooms()
        break
      }
      case 'subscribed':
      case 'unsubscribed':
      case 'pong':
      case 'unsupported_event':
        // 元事件，忽略
        break
      default:
        if (typeof eventType === 'string' && eventType.startsWith('chatroom_')) {
          // 未识别的 chatroom 事件提示一下，不让 UI 崩
          console.warn('[chatroom] unhandled event', eventType, data)
        }
        break
    }
  }, [loadActiveRoom, loadRooms])

  const subscribeRef = useRef<((data: unknown) => void) | null>(null)

  const handleWSConnect = useCallback(() => {
    // 重连后重新订阅当前房间
    const roomId = activeRoomIdRef.current
    const send = subscribeRef.current
    if (roomId && send) {
      send({ event_type: 'subscribe', channel: `chatroom:${roomId}` })
      subscribedRoomIdRef.current = roomId
    }
  }, [])

  const { send } = useWebSocket({
    url: wsUrl,
    onMessage: handleWSMessage,
    onConnect: handleWSConnect,
  })
  subscribeRef.current = send

  // 切换房间时订阅/退订
  useEffect(() => {
    const newRoomId = activeRoom?.id || null
    const previous = subscribedRoomIdRef.current
    if (previous && previous !== newRoomId) {
      send({ event_type: 'unsubscribe', channel: `chatroom:${previous}` })
      subscribedRoomIdRef.current = null
    }
    if (newRoomId && previous !== newRoomId) {
      send({ event_type: 'subscribe', channel: `chatroom:${newRoomId}` })
      subscribedRoomIdRef.current = newRoomId
    }
    return () => {
      // 组件卸载时清理
    }
  }, [activeRoom?.id, send])

  useEffect(() => {
    return () => {
      const previous = subscribedRoomIdRef.current
      const fn = subscribeRef.current
      if (previous && fn) {
        fn({ event_type: 'unsubscribe', channel: `chatroom:${previous}` })
        subscribedRoomIdRef.current = null
      }
    }
  }, [])

  // 自动滚到底部
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [activeRoom?.messages?.length])

  // ─── 派生数据 ───────────────────────────────────────────
  const allMemberNames = useMemo(() => {
    if (!activeRoom) return [] as string[]
    const names = [...activeRoom.members]
    for (const m of activeRoom.dynamic_members) {
      if (m.name && !names.includes(m.name)) names.push(m.name)
    }
    return names
  }, [activeRoom])

  const agentMeta: AgentMetaMap = useMemo(
    () => agentMetaFromList(agents),
    [agents],
  )

  const settings = activeRoom?.settings || DEFAULT_SETTINGS

  // ─── 输入框：@ 提及浮窗 ─────────────────────────────────
  const updateMentionPicker = useCallback(
    (text: string, cursorPos: number) => {
      // 找到光标前最近的 @，且 @ 之后没有空白
      let i = cursorPos - 1
      let foundAt = -1
      while (i >= 0) {
        const ch = text[i]
        if (ch === '@') {
          foundAt = i
          break
        }
        if (ch === ' ' || ch === '\n' || ch === '\t') break
        i -= 1
      }
      if (foundAt === -1) {
        setMentionPicker({ visible: false, query: '', position: 0 })
        return
      }
      const query = text.slice(foundAt + 1, cursorPos)
      setMentionPicker({ visible: true, query, position: foundAt })
    },
    []
  )

  const handleInputChange = (
    event: React.ChangeEvent<HTMLTextAreaElement>
  ) => {
    const next = event.target.value
    setInput(next)
    const cursor = event.target.selectionStart || next.length
    updateMentionPicker(next, cursor)
  }

  const insertMention = (name: string) => {
    if (!mentionPicker.visible) {
      setInput((prev) => `${prev}@${name} `)
      return
    }
    const before = input.slice(0, mentionPicker.position)
    // 跳过原来的 @ + query
    const afterStart = mentionPicker.position + 1 + mentionPicker.query.length
    const after = input.slice(afterStart)
    const next = `${before}@${name} ${after}`
    setInput(next)
    setMentionPicker({ visible: false, query: '', position: 0 })
    // 还原焦点
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (el) {
        el.focus()
        const cursor = (before + `@${name} `).length
        el.setSelectionRange(cursor, cursor)
      }
    })
  }

  const filteredMentionCandidates = useMemo(() => {
    if (!activeRoom) return [] as string[]
    const q = mentionPicker.query.toLowerCase()
    return allMemberNames.filter((name) =>
      q ? name.toLowerCase().includes(q) : true
    )
  }, [activeRoom, mentionPicker.query, allMemberNames])

  const detectedMentions = useMemo(() => {
    if (!input || allMemberNames.length === 0) return [] as string[]
    const re = new RegExp(MENTION_REGEX.source, 'g')
    const set = new Set<string>()
    let match: RegExpExecArray | null
    while ((match = re.exec(input)) !== null) {
      if (allMemberNames.includes(match[1])) set.add(match[1])
    }
    return Array.from(set)
  }, [input, allMemberNames])

  // ─── 发送消息 ───────────────────────────────────────────
  const handleSend = async () => {
    const text = input.trim()
    if (!text || !activeRoom || sending) return
    setSending(true)
    setError('')
    const res = await api.postChatroomMessage(activeRoom.id, text)
    setSending(false)
    if (res.status !== 'ok' || !res.data) {
      setError(res.message || '发送失败')
      return
    }
    // 用户消息已经写入后端；后端会广播事件，本地直接 append 也无妨
    setActiveRoom((prev) =>
      prev
        ? { ...prev, messages: mergeMessage(prev.messages, res.data!.message) }
        : prev
    )
    setInput('')
    setMentionPicker({ visible: false, query: '', position: 0 })
  }

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionPicker.visible && event.key === 'Enter' && !event.shiftKey) {
      const first = filteredMentionCandidates[0]
      if (first) {
        event.preventDefault()
        insertMention(first)
        return
      }
    }
    if (event.key === 'Enter' && !event.shiftKey && !sending) {
      event.preventDefault()
      handleSend()
    }
    if (event.key === 'Escape' && mentionPicker.visible) {
      setMentionPicker({ visible: false, query: '', position: 0 })
    }
  }

  // ─── 房间增删改 ─────────────────────────────────────────
  const handleCreate = async (payload: ChatroomCreatePayload) => {
    const res = await api.createChatroom(payload)
    if (res.status === 'ok' && res.data) {
      await loadRooms(res.data.id)
      setActiveRoom(res.data)
      setShowCreateModal(false)
    } else {
      setError(res.message || '创建失败')
    }
  }

  const handleDelete = async (roomId: string) => {
    if (!window.confirm('删除聊天室？所有消息将丢失。')) return
    const res = await api.deleteChatroom(roomId)
    if (res.status === 'ok') {
      if (selectedRoomId === roomId) {
        setSelectedRoomId(null)
        setActiveRoom(null)
      }
      await loadRooms()
    } else {
      setError(res.message || '删除失败')
    }
  }

  const handleUpdateRoom = async (payload: ChatroomUpdatePayload) => {
    if (!activeRoom) return
    const res = await api.updateChatroom(activeRoom.id, payload)
    if (res.status === 'ok' && res.data) {
      setActiveRoom(res.data)
      await loadRooms(activeRoom.id)
    } else {
      setError(res.message || '更新失败')
    }
  }

  const handleAddMember = async (name: string) => {
    if (!activeRoom || !name) return
    if (allMemberNames.includes(name)) return
    await handleUpdateRoom({ members: [...activeRoom.members, name] })
  }

  const handleRemoveMember = async (name: string) => {
    if (!activeRoom) return
    if (activeRoom.members.includes(name)) {
      await handleUpdateRoom({
        members: activeRoom.members.filter((m) => m !== name),
      })
      return
    }
    if (activeRoom.dynamic_members.some((m) => m.name === name)) {
      await handleUpdateRoom({
        dynamic_members: activeRoom.dynamic_members.filter(
          (m) => m.name !== name
        ),
      })
    }
  }

  const handleRetry = async (message: ChatroomMessage) => {
    if (!activeRoom) return
    if (!message.sender.startsWith('agent:')) return
    const agentName = message.sender.slice(6)
    if (!agentName) return
    const prompt = (message.meta as any)?.prompt || ''
    const res = await api.invokeChatroom(activeRoom.id, agentName, prompt)
    if (res.status !== 'ok') {
      setError(res.message || '重试失败')
    }
  }

  const handleCancelAll = async () => {
    if (!activeRoom) return
    const res = await api.cancelChatroom(activeRoom.id)
    if (res.status !== 'ok') {
      setError(res.message || '取消失败')
    }
  }

  // ─── 渲染 ───────────────────────────────────────────────
  return (
    <div className="page chatroom-page">
      <div className="page__header">
        <div>
          <h1 className="page__title">聊天室</h1>
          <div className="page__subtitle">
            多 Agent 群聊。@ 召唤成员接力、设置房间目标、绑定工作区。
          </div>
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

      <div className="chatroom-shell">
        <ChatroomList
          rooms={rooms}
          selectedId={selectedRoomId}
          onSelect={(id) => setSelectedRoomId(id)}
          onDelete={handleDelete}
          onCreate={() => setShowCreateModal(true)}
        />

        <section className="chatroom-main">
          {activeRoom ? (
            <>
              <ChatroomBanner
                room={activeRoom}
                expanded={showBannerDetails}
                onToggle={() => setShowBannerDetails((v) => !v)}
              />

              <div className="chatroom-transcript" ref={transcriptRef}>
                {activeRoom.messages.length === 0 ? (
                  <div className="empty-state" style={{ padding: 60 }}>
                    <strong>开始对话</strong>
                    <span>
                      @ 一名成员让 ta 发言，或直接写需求让大家协作。
                    </span>
                  </div>
                ) : (
                  activeRoom.messages.map((message) => (
                    <ChatroomMessageCard
                      key={message.id}
                      message={message}
                      onRetry={handleRetry}
                      agentMeta={agentMeta}
                    />
                  ))
                )}
              </div>

              <ChatroomComposer
                value={input}
                onChange={handleInputChange}
                onKeyDown={onInputKeyDown}
                onSend={handleSend}
                inputRef={inputRef}
                sending={sending}
                mentionPicker={mentionPicker}
                mentionCandidates={filteredMentionCandidates}
                onPickMention={insertMention}
                detectedMentions={detectedMentions}
                autoHost={settings.auto_host}
              />
            </>
          ) : (
            <div className="empty-state" style={{ padding: 80 }}>
              <strong>未选择房间</strong>
              <span>从左侧选择一个房间，或新建一个聊天室。</span>
            </div>
          )}
        </section>

        <ChatroomSidePanel
          room={activeRoom}
          agents={agents}
          workspaces={state.workspaces}
          onAddMember={handleAddMember}
          onRemoveMember={handleRemoveMember}
          onUpdate={handleUpdateRoom}
          onCancelAll={handleCancelAll}
        />
      </div>

      {showCreateModal && (
        <ChatroomCreateModal
          agents={agents}
          workspaces={state.workspaces}
          defaultWorkspaceId={state.selectedWorkspace?.id || null}
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreate}
        />
      )}
    </div>
  )
}

// ─── 子组件：房间列表 ────────────────────────────────────

interface ChatroomListProps {
  rooms: ChatroomSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onCreate: () => void
}

function ChatroomList({
  rooms,
  selectedId,
  onSelect,
  onDelete,
  onCreate,
}: ChatroomListProps) {
  return (
    <aside className="chatroom-list">
      <div className="chatroom-list__header">
        <span style={{ fontWeight: 600 }}>聊天室列表</span>
        <button type="button" className="btn-xs" onClick={onCreate}>
          + 新建
        </button>
      </div>
      <div className="chatroom-list__body">
        {rooms.length === 0 ? (
          <div className="empty-state" style={{ padding: 18 }}>
            <strong>还没有聊天室</strong>
            <span>点击右上角「+ 新建」创建。</span>
          </div>
        ) : (
          rooms.map((room) => (
            <div
              key={room.id}
              className={`chatroom-list-row ${
                selectedId === room.id ? 'chatroom-list-row--active' : ''
              }`}
              onClick={() => onSelect(room.id)}
            >
              <div className="chatroom-list-row__title">
                {room.title || '未命名房间'}
              </div>
              {room.topic && (
                <div className="chatroom-list-row__topic">{room.topic}</div>
              )}
              <div className="chatroom-list-row__meta">
                <span>{room.members.length} 成员</span>
                <span>{room.message_count} 消息</span>
                <span>{formatDate(room.last_message_at || room.updated_at)}</span>
              </div>
              <button
                type="button"
                className="chatroom-list-row__delete"
                onClick={(event) => {
                  event.stopPropagation()
                  onDelete(room.id)
                }}
                title="删除"
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
                </svg>
              </button>
            </div>
          ))
        )}
      </div>
    </aside>
  )
}

// ─── 子组件：banner ─────────────────────────────────────

function ChatroomBanner({
  room,
  expanded,
  onToggle,
}: {
  room: Chatroom
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <header className="chatroom-banner">
      <div className="chatroom-banner__row" onClick={onToggle}>
        <div className="chatroom-banner__title">
          <span className="chatroom-banner__name">{room.title}</span>
          {room.workspace_id && (
            <span className="chatroom-banner__workspace">
              工作区 · {room.workspace_id}
            </span>
          )}
        </div>
        <button type="button" className="btn-xs" onClick={onToggle}>
          {expanded ? '收起' : '展开'}
        </button>
      </div>
      <div className="chatroom-banner__topic">
        <span className="chatroom-banner__label">主题</span>
        <span className="chatroom-banner__value">
          {room.topic || '（未设定）'}
        </span>
      </div>
      <div className="chatroom-banner__goal">
        <span className="chatroom-banner__label">当前目标</span>
        <span className="chatroom-banner__goal-text">
          {room.goal || '（未设定）'}
        </span>
      </div>
      {expanded && room.goal_history && room.goal_history.length > 0 && (
        <div className="chatroom-banner__history">
          <div className="chatroom-banner__label">目标历史</div>
          {room.goal_history.map((entry, i) => (
            <div key={i} className="chatroom-banner__history-row">
              <span className="text-muted">{formatDate(entry.set_at)}</span>
              <span className="chatroom-banner__history-by">{entry.set_by}</span>
              <span>{entry.goal}</span>
            </div>
          ))}
        </div>
      )}
      {expanded && room.summary && (
        <div className="chatroom-banner__summary">
          <div className="chatroom-banner__label">背景摘要</div>
          <div>{room.summary}</div>
        </div>
      )}
    </header>
  )
}

// ─── 子组件：消息卡片 ────────────────────────────────────

function ChatroomMessageCard({
  message,
  onRetry,
  agentMeta,
}: {
  message: ChatroomMessage
  onRetry: (m: ChatroomMessage) => void
  agentMeta: AgentMetaMap
}) {
  const [expanded, setExpanded] = useState(false)
  const isAgent = senderIsAgent(message.sender)
  const isUser = message.sender === 'user'
  const isSystem = message.sender === 'system'
  const senderInfo = senderToDisplay(message.sender, agentMeta)
  const displayName = senderInfo.name
  const modelBadge = senderInfo.model
  const color = isAgent || (!isUser && !isSystem) ? hashColor(displayName) : undefined
  const meta: any = message.meta || {}
  const elapsedMs = meta.elapsed_ms
  const tokens = meta.usage?.total_tokens
  const toolCount =
    (message.tool_calls?.length || 0) ||
    (typeof meta.tool_count === 'number' ? meta.tool_count : 0)
  const thinking = message.thinking_buffer || ''
  const toolCalls = message.tool_calls || []
  const showFold = isAgent && (thinking.length > 0 || toolCalls.length > 0)

  return (
    <div
      className={[
        'chatroom-msg',
        `chatroom-msg--${isUser ? 'user' : isSystem ? 'system' : 'agent'}`,
        message.status === 'failed' ? 'chatroom-msg--failed' : '',
        message.status === 'streaming' ? 'chatroom-msg--streaming' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="chatroom-msg__head">
        <div
          className="chatroom-msg__avatar"
          style={{
            background: color || (isUser ? '#5e574e' : '#948b80'),
          }}
        >
          {avatarLabel(displayName)}
        </div>
        <div className="chatroom-msg__head-text">
          <span className="chatroom-msg__name">{displayName}</span>
          {modelBadge && (
            <small className="agent-model-badge" title={`LLM 模型：${modelBadge}`}>
              {modelBadge}
            </small>
          )}
          {statusLabel(message.status) && (
            <span
              className={`chatroom-msg__badge chatroom-msg__badge--${message.status}`}
            >
              {statusLabel(message.status)}
            </span>
          )}
          <span className="chatroom-msg__time">
            {formatTime(message.created_at)}
          </span>
        </div>
        <div className="chatroom-msg__head-meta">
          {elapsedMs != null && (
            <span className="chatroom-msg__stat">
              {(Number(elapsedMs) / 1000).toFixed(1)}s
            </span>
          )}
          {toolCount > 0 && (
            <span className="chatroom-msg__stat">{toolCount} 次工具</span>
          )}
          {tokens != null && (
            <span className="chatroom-msg__stat">{tokens} tokens</span>
          )}
        </div>
      </div>

      {showFold && (
        <div className="chatroom-msg__fold">
          <button
            type="button"
            className="chatroom-msg__fold-toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '收起思考过程' : `展开思考过程 (${toolCalls.length} 次工具)`}
          </button>
          {expanded && (
            <div className="chatroom-msg__fold-body">
              {thinking && (
                <pre className="chatroom-msg__thinking">{thinking}</pre>
              )}
              {toolCalls.map((call) => (
                <ToolCallCard key={call.tool_call_id} call={call} />
              ))}
            </div>
          )}
        </div>
      )}

      {message.content ? (
        <MarkdownBody content={message.content} />
      ) : message.status === 'pending' || message.status === 'streaming' ? (
        <div className="chatroom-msg__body chatroom-msg__body--placeholder">
          <span className="chatroom-typing">
            <span />
            <span />
            <span />
          </span>
        </div>
      ) : null}

      {message.status === 'failed' && (
        <div className="chatroom-msg__retry">
          <span className="chatroom-msg__error">
            {/* A6/R2: 流式中断专属文案 — 区别于普通调用失败，告诉用户点击重试 */}
            {(() => {
              const err = (meta.error as string) || ''
              if (/stream/i.test(err)) {
                return '流式中断，请点击重试'
              }
              return err || '调用失败'
            })()}
          </span>
          {isAgent && (
            <button type="button" className="btn-xs" onClick={() => onRetry(message)}>
              重试
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function ToolCallCard({ call }: { call: ChatroomToolCallRecord }) {
  const [open, setOpen] = useState(false)
  const argsText = useMemo(() => {
    try {
      return JSON.stringify(call.args, null, 2)
    } catch {
      return String(call.args ?? '')
    }
  }, [call.args])
  const argsBrief = useMemo(() => {
    if (!argsText) return ''
    if (argsText.length <= 80) return argsText.replace(/\s+/g, ' ')
    return argsText.replace(/\s+/g, ' ').slice(0, 80) + '…'
  }, [argsText])
  const resultText = useMemo(() => {
    try {
      return typeof call.result_preview === 'string'
        ? call.result_preview
        : JSON.stringify(call.result_preview, null, 2)
    } catch {
      return String(call.result_preview ?? '')
    }
  }, [call.result_preview])

  return (
    <div
      className={`chatroom-tool ${
        call.status === 'error' ? 'chatroom-tool--error' : ''
      }`}
    >
      <div className="chatroom-tool__head">
        <span className="chatroom-tool__name">⚙ {call.tool_name}</span>
        <span className="chatroom-tool__args">{argsBrief}</span>
        <span className="chatroom-tool__status">
          {call.status === 'running'
            ? '运行中'
            : call.status === 'error'
            ? '错误'
            : '完成'}
          {typeof call.elapsed_ms === 'number' &&
            ` · ${(call.elapsed_ms / 1000).toFixed(1)}s`}
        </span>
        <button
          type="button"
          className="btn-xs"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? '收起' : '详情'}
        </button>
      </div>
      {open && (
        <div className="chatroom-tool__body">
          {argsText && (
            <>
              <div className="chatroom-tool__label">参数</div>
              <pre>{argsText}</pre>
            </>
          )}
          {call.result_preview != null && (
            <>
              <div className="chatroom-tool__label">结果</div>
              <pre>{resultText}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ─── 子组件：输入框 ─────────────────────────────────────

interface ComposerProps {
  value: string
  onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) => void
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void
  onSend: () => void
  inputRef: React.RefObject<HTMLTextAreaElement>
  sending: boolean
  mentionPicker: { visible: boolean; query: string; position: number }
  mentionCandidates: string[]
  onPickMention: (name: string) => void
  detectedMentions: string[]
  autoHost: boolean
}

function ChatroomComposer({
  value,
  onChange,
  onKeyDown,
  onSend,
  inputRef,
  sending,
  mentionPicker,
  mentionCandidates,
  onPickMention,
  detectedMentions,
  autoHost,
}: ComposerProps) {
  const hint =
    detectedMentions.length === 0
      ? autoHost
        ? '未 @ 任何 Agent，将由 host 决定调度'
        : '未 @ 任何 Agent，将不会触发回复'
      : `将召唤 ${detectedMentions.map((n) => `@${n}`).join(' ')} 接力`

  return (
    <div className="chatroom-composer">
      <div className="chatroom-composer__input-wrap">
        <textarea
          ref={inputRef}
          className="chatroom-composer__input"
          value={value}
          onChange={onChange}
          onKeyDown={onKeyDown}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行。@ 召唤成员"
          rows={3}
          disabled={sending}
        />
        {mentionPicker.visible && mentionCandidates.length > 0 && (
          <div className="chatroom-mention-picker">
            {mentionCandidates.slice(0, 8).map((name) => (
              <button
                key={name}
                type="button"
                className="chatroom-mention-picker__item"
                onClick={() => onPickMention(name)}
              >
                <span
                  className="chatroom-mention-picker__avatar"
                  style={{ background: hashColor(name) }}
                >
                  {avatarLabel(name)}
                </span>
                <span>{name}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="chatroom-composer__actions">
        <span className="text-muted" style={{ fontSize: 11.5 }}>
          {hint}
        </span>
        <button
          type="button"
          className="btn-primary"
          onClick={onSend}
          disabled={!value.trim() || sending}
        >
          {sending ? '发送中…' : '发送'}
        </button>
      </div>
    </div>
  )
}

// ─── 子组件：右栏成员/设置 ──────────────────────────────

interface SidePanelProps {
  room: Chatroom | null
  agents: AgentInfo[]
  workspaces: ManagedWorkspace[]
  onAddMember: (name: string) => void
  onRemoveMember: (name: string) => void
  onUpdate: (payload: ChatroomUpdatePayload) => void
  onCancelAll: () => void
}

function ChatroomSidePanel({
  room,
  agents,
  workspaces,
  onAddMember,
  onRemoveMember,
  onUpdate,
  onCancelAll,
}: SidePanelProps) {
  const [draftMember, setDraftMember] = useState('')
  const [topicDraft, setTopicDraft] = useState(room?.topic || '')
  const [goalDraft, setGoalDraft] = useState(room?.goal || '')

  useEffect(() => {
    setTopicDraft(room?.topic || '')
    setGoalDraft(room?.goal || '')
  }, [room?.id, room?.topic, room?.goal])

  if (!room) {
    return (
      <aside className="chatroom-side">
        <div className="empty-state" style={{ padding: 18 }}>
          <strong>未选择房间</strong>
        </div>
      </aside>
    )
  }

  const allMembers = [...room.members, ...room.dynamic_members.map((m) => m.name)]
  const settings = room.settings || DEFAULT_SETTINGS

  const candidateAgents = agents.filter((a) => !allMembers.includes(a.name))

  return (
    <aside className="chatroom-side">
      <div className="chatroom-side__section">
        <div className="chatroom-side__title">成员（{allMembers.length}）</div>
        <div className="chatroom-side__members">
          {room.members.map((name) => (
            <MemberRow
              key={`s-${name}`}
              name={name}
              dynamic={false}
              onRemove={() => onRemoveMember(name)}
            />
          ))}
          {room.dynamic_members.map((m) => (
            <MemberRow
              key={`d-${m.name}`}
              name={m.name}
              dynamic
              tooltip={m.role_prompt}
              onRemove={() => onRemoveMember(m.name)}
            />
          ))}
        </div>
        <div className="chatroom-side__add-member">
          <Select
            size="sm"
            fullWidth
            value={draftMember}
            onChange={(v) => setDraftMember(v)}
            placeholder={candidateAgents.length ? '添加成员…' : '已无可加成员'}
            disabled={candidateAgents.length === 0}
            options={candidateAgents.map((a) => ({
              value: a.name,
              label: a.name,
              description: a.description || '',
            }))}
          />
          <button
            type="button"
            className="btn-xs"
            disabled={!draftMember}
            onClick={() => {
              if (draftMember) {
                onAddMember(draftMember)
                setDraftMember('')
              }
            }}
          >
            添加
          </button>
        </div>
      </div>

      <div className="chatroom-side__section">
        <div className="chatroom-side__title">主题 / 目标</div>
        <textarea
          className="chatroom-side__textarea"
          value={topicDraft}
          rows={3}
          onChange={(e) => setTopicDraft(e.target.value)}
          onBlur={() => {
            if (topicDraft !== room.topic) onUpdate({ topic: topicDraft })
          }}
          placeholder="房间主题（长文本）"
        />
        <input
          type="text"
          className="chatroom-side__input"
          value={goalDraft}
          onChange={(e) => setGoalDraft(e.target.value)}
          onBlur={() => {
            if (goalDraft !== (room.goal || ''))
              onUpdate({ goal: goalDraft || null })
          }}
          placeholder="当前目标（单行）"
        />
      </div>

      <div className="chatroom-side__section">
        <div className="chatroom-side__title">工作区绑定</div>
        <Select
          size="sm"
          fullWidth
          value={room.workspace_id || ''}
          onChange={(v) => onUpdate({ workspace_id: v || null })}
          placeholder="未绑定"
          options={[
            { value: '', label: '未绑定' },
            ...workspaces.map((w) => ({
              value: w.id,
              label: w.name,
              description: w.root_path,
            })),
          ]}
        />
      </div>

      <div className="chatroom-side__section">
        <div className="chatroom-side__title">设置</div>
        <SettingsForm settings={settings} agents={allMembers} onUpdate={onUpdate} />
      </div>

      <div className="chatroom-side__section">
        <div className="chatroom-side__title">操作</div>
        <button type="button" className="btn-secondary" onClick={onCancelAll}>
          取消所有进行中发言
        </button>
      </div>
    </aside>
  )
}

function MemberRow({
  name,
  dynamic,
  tooltip,
  onRemove,
}: {
  name: string
  dynamic: boolean
  tooltip?: string
  onRemove: () => void
}) {
  return (
    <div className="chatroom-member" title={tooltip || ''}>
      <span
        className="chatroom-member__avatar"
        style={{ background: hashColor(name) }}
      >
        {avatarLabel(name)}
      </span>
      <span className="chatroom-member__name">
        {name}
        {dynamic && <span className="chatroom-member__tag">[动态]</span>}
      </span>
      <button
        type="button"
        className="chatroom-member__remove"
        onClick={onRemove}
        title="移除"
      >
        ×
      </button>
    </div>
  )
}

function SettingsForm({
  settings,
  agents,
  onUpdate,
}: {
  settings: ChatroomSettings
  agents: string[]
  onUpdate: (payload: ChatroomUpdatePayload) => void
}) {
  const apply = (patch: Partial<ChatroomSettings>) => {
    onUpdate({ settings: { ...settings, ...patch } })
  }
  const autoHostMeta = getSettingLabel('auto_host')
  const hostAgentMeta = getSettingLabel('host_agent')
  const recentNMeta = getSettingLabel('recent_n')
  const summaryMeta = getSettingLabel('summary_threshold_m')
  const relayMeta = getSettingLabel('max_relay_depth')
  const membersMeta = getSettingLabel('max_members')
  const inviteMeta = getSettingLabel('allow_agent_invite')
  return (
    <div className="chatroom-settings">
      <label className="chatroom-settings__row">
        <div className="chatroom-settings__label">
          <span>{autoHostMeta.label}</span>
          {autoHostMeta.hint && (
            <small className="chatroom-settings__hint">{autoHostMeta.hint}</small>
          )}
        </div>
        <input
          type="checkbox"
          checked={settings.auto_host}
          onChange={(e) => apply({ auto_host: e.target.checked })}
        />
      </label>
      <label className="chatroom-settings__row">
        <div className="chatroom-settings__label">
          <span>{hostAgentMeta.label}</span>
          {hostAgentMeta.hint && (
            <small className="chatroom-settings__hint">{hostAgentMeta.hint}</small>
          )}
        </div>
        <Select
          size="sm"
          fullWidth={false}
          value={settings.host_agent}
          onChange={(v) => apply({ host_agent: v })}
          options={[
            { value: 'planner', label: 'planner' },
            ...agents.map((a) => ({ value: a, label: a })),
          ].filter(
            (item, idx, arr) => arr.findIndex((x) => x.value === item.value) === idx
          )}
        />
      </label>
      <NumberSetting
        label={recentNMeta.label}
        hint={recentNMeta.hint}
        value={settings.recent_n}
        onChange={(v) => apply({ recent_n: v })}
      />
      <NumberSetting
        label={summaryMeta.label}
        hint={summaryMeta.hint}
        value={settings.summary_threshold_m}
        onChange={(v) => apply({ summary_threshold_m: v })}
      />
      <NumberSetting
        label={relayMeta.label}
        hint={relayMeta.hint}
        value={settings.max_relay_depth}
        onChange={(v) => apply({ max_relay_depth: v })}
      />
      <NumberSetting
        label={membersMeta.label}
        hint={membersMeta.hint}
        value={settings.max_members}
        onChange={(v) => apply({ max_members: v })}
      />
      <label className="chatroom-settings__row">
        <div className="chatroom-settings__label">
          <span>{inviteMeta.label}</span>
          {inviteMeta.hint && (
            <small className="chatroom-settings__hint">{inviteMeta.hint}</small>
          )}
        </div>
        <input
          type="checkbox"
          checked={settings.allow_agent_invite}
          onChange={(e) => apply({ allow_agent_invite: e.target.checked })}
        />
      </label>
    </div>
  )
}

function NumberSetting({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint?: string
  value: number
  onChange: (v: number) => void
}) {
  const [draft, setDraft] = useState(String(value ?? 0))
  useEffect(() => {
    setDraft(String(value ?? 0))
  }, [value])
  return (
    <label className="chatroom-settings__row">
      <div className="chatroom-settings__label">
        <span>{label}</span>
        {hint && <small className="chatroom-settings__hint">{hint}</small>}
      </div>
      <input
        type="number"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const n = Number(draft)
          if (!Number.isNaN(n) && n !== value) onChange(n)
          else setDraft(String(value))
        }}
        style={{ width: 80 }}
      />
    </label>
  )
}

// ─── 子组件：创建房间 modal ─────────────────────────────

function ChatroomCreateModal({
  agents,
  workspaces,
  defaultWorkspaceId,
  onClose,
  onSubmit,
}: {
  agents: AgentInfo[]
  workspaces: ManagedWorkspace[]
  defaultWorkspaceId: string | null
  onClose: () => void
  onSubmit: (payload: ChatroomCreatePayload) => void
}) {
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [goal, setGoal] = useState('')
  const [members, setMembers] = useState<string[]>([])
  const [workspaceId, setWorkspaceId] = useState<string>(defaultWorkspaceId || '')
  const [submitting, setSubmitting] = useState(false)

  const toggleMember = (name: string) => {
    setMembers((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    )
  }

  const handleSubmit = async () => {
    if (!title.trim()) return
    setSubmitting(true)
    onSubmit({
      title: title.trim(),
      topic: topic.trim(),
      goal: goal.trim() || null,
      members,
      workspace_id: workspaceId || null,
    })
    setSubmitting(false)
  }

  return (
    <div className="chatroom-modal__backdrop" onClick={onClose}>
      <div
        className="chatroom-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="chatroom-modal__header">
          <h3>新建聊天室</h3>
          <button className="btn-xs" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="chatroom-modal__body">
          <label className="chatroom-modal__field">
            <span>房间名 *</span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例：毕设讨论组"
            />
          </label>
          <label className="chatroom-modal__field">
            <span>主题 *</span>
            <textarea
              value={topic}
              rows={3}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="房间主题（长文本，所有 Agent 都能看到）"
            />
          </label>
          <label className="chatroom-modal__field">
            <span>目标</span>
            <input
              type="text"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="当前主要目标（可选）"
            />
          </label>
          <div className="chatroom-modal__field">
            <span>成员（多选）</span>
            <div className="chatroom-modal__agents">
              {agents.length === 0 ? (
                <span className="text-muted">暂无可选 Agent</span>
              ) : (
                agents.map((agent) => {
                  const active = members.includes(agent.name)
                  return (
                    <button
                      key={agent.name}
                      type="button"
                      className={`chatroom-modal__agent ${
                        active ? 'chatroom-modal__agent--active' : ''
                      }`}
                      onClick={() => toggleMember(agent.name)}
                    >
                      <span
                        className="chatroom-modal__agent-avatar"
                        style={{ background: hashColor(agent.name) }}
                      >
                        {avatarLabel(agent.name)}
                      </span>
                      <span>{agent.name}</span>
                    </button>
                  )
                })
              )}
            </div>
          </div>
          <label className="chatroom-modal__field">
            <span>工作区</span>
            <Select
              size="sm"
              fullWidth
              value={workspaceId}
              onChange={(v) => setWorkspaceId(v)}
              placeholder="未绑定"
              options={[
                { value: '', label: '未绑定' },
                ...workspaces.map((w) => ({
                  value: w.id,
                  label: w.name,
                  description: w.root_path,
                })),
              ]}
            />
          </label>
        </div>
        <div className="chatroom-modal__footer">
          <button className="btn-secondary" onClick={onClose}>
            取消
          </button>
          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={!title.trim() || !topic.trim() || submitting}
          >
            创建
          </button>
        </div>
      </div>
    </div>
  )
}

export default ChatroomPanel
