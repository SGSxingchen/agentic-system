import { useState, useEffect, useRef, useCallback } from 'react'
import { useAppStore } from '../store/appStore'
import type { Message } from '../types'
import './ChatPanel.css'

const API_BASE = 'http://localhost:8001'

// ===== Simple Markdown Renderer =====

function renderMarkdown(text: string): string {
  // Escape HTML
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks (```...```)
  html = html.replace(
    /```(\w*)\n?([\s\S]*?)```/g,
    (_match, _lang, code) =>
      `<pre class="md-code-block"><code>${code.trim()}</code></pre>`
  )

  // Inline code (`...`)
  html = html.replace(
    /`([^`]+)`/g,
    '<code class="md-inline-code">$1</code>'
  )

  // Bold (**...**)
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // Italic (*...*)
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Line breaks
  html = html.replace(/\n/g, '<br/>')

  return html
}

export function ChatPanel() {
  const { state, dispatch } = useAppStore()
  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  // 流式累积文本
  const [streamingText, setStreamingText] = useState('')
  const [streamingTools, setStreamingTools] = useState<{ tool: string; status: 'calling' | 'done'; result?: string }[]>([])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || state.sending) return

    setInput('')
    setStreamingText('')
    setStreamingTools([])

    // 添加用户消息
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      type: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    dispatch({ type: 'ADD_MESSAGE', payload: userMsg })
    dispatch({ type: 'SET_SENDING', payload: true })

    try {
      // 尝试流式端点
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
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

            if (event.type === 'thinking' && event.content) {
              fullText += event.content
              setStreamingText(fullText)
              console.log('[STREAM] text:', fullText.length, 'chars')
            } else if (event.type === 'tool_call') {
              setStreamingTools((prev) => [
                ...prev,
                { tool: event.tool, status: 'calling' },
              ])
            } else if (event.type === 'tool_result') {
              setStreamingTools((prev) =>
                prev.map((t) =>
                  t.tool === event.tool && t.status === 'calling'
                    ? { ...t, status: 'done' as const, result: typeof event.result === 'string' ? event.result : JSON.stringify(event.result).slice(0, 100) }
                    : t
                )
              )
            } else if (event.type === 'done') {
              if (event.content) {
                if (typeof event.content === 'string') {
                  finalContent = event.content
                } else if (event.content.response) {
                  finalContent = event.content.response
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
      const assistantMsg: Message = {
        id: `assistant-${Date.now()}`,
        type: 'assistant',
        content: responseText,
        timestamp: new Date().toISOString(),
      }
      dispatch({ type: 'ADD_MESSAGE', payload: assistantMsg })
      setStreamingText('')
      setStreamingTools([])

    } catch (err) {
      // fallback: 非流式
      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text }),
        })
        if (res.ok) {
          const data = await res.json()
          const responseText = data.response || data.content || JSON.stringify(data)
          dispatch({
            type: 'ADD_MESSAGE',
            payload: {
              id: `assistant-${Date.now()}`,
              type: 'assistant',
              content: responseText,
              timestamp: new Date().toISOString(),
            },
          })
          setStreamingText('')
          setStreamingTools([])
          return
        }
      } catch { /* ignore fallback error */ }

      dispatch({
        type: 'ADD_MESSAGE',
        payload: {
          id: `error-${Date.now()}`,
          type: 'system',
          content: `${err instanceof Error ? err.message : '发送失败'}`,
          timestamp: new Date().toISOString(),
        },
      })
      setStreamingText('')
      setStreamingTools([])
    } finally {
      dispatch({ type: 'SET_SENDING', payload: false })
    }
  }, [input, state.sending, dispatch])

  // Auto-scroll
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [state.messages, streamingText, streamingTools])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-panel">
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
            <p>发送消息开始与 AI 智能体交互</p>
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
                  <div
                    className="chat-bubble-text"
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(msg.content),
                    }}
                  />
                  {msg.memoriesUsed != null && msg.memoriesUsed > 0 && (
                    <div className="chat-memory-indicator">
                      使用了 {msg.memoriesUsed} 条记忆
                    </div>
                  )}
                  <div className="chat-bubble-time">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              )}
            </div>
          ))
        )}

        {/* 流式输出区域 */}
        {state.sending && (streamingText || streamingTools.length > 0) && (
          <div className="chat-row chat-row-assistant">
            <div className="chat-avatar">A</div>
            <div className="chat-bubble chat-bubble-assistant">
              {streamingTools.length > 0 && (
                <div className="chat-tool-tags">
                  {streamingTools.map((t, i) => (
                    <span key={i} className={`chat-tool-tag chat-tool-tag--${t.status}`}>
                      {t.status === 'calling' ? '...' : '.'} {t.tool}
                    </span>
                  ))}
                </div>
              )}
              {streamingText && (
                <div
                  className="chat-bubble-text"
                  dangerouslySetInnerHTML={{
                    __html: renderMarkdown(streamingText),
                  }}
                />
              )}
              <span className="streaming-cursor" />
            </div>
          </div>
        )}

        {/* 等待中指示器（还没收到任何流事件） */}
        {state.sending && !streamingText && streamingTools.length === 0 && (
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
            disabled={state.sending}
          />
          <button
            className="chat-send-btn"
            onClick={handleSend}
            disabled={!input.trim() || state.sending}
          >
            {state.sending ? (
              <span className="send-spinner" />
            ) : (
              '发送'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
