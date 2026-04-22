import { useEffect, useRef, useCallback } from 'react'

interface UseWebSocketOptions {
  url: string
  onMessage?: (data: unknown) => void
  onConnect?: () => void
  onDisconnect?: () => void
  reconnect?: boolean
  maxReconnectDelay?: number
}

interface UseWebSocketReturn {
  send: (data: unknown) => void
  connected: boolean
}

export function useWebSocket({
  url,
  onMessage,
  onConnect,
  onDisconnect,
  reconnect = true,
  maxReconnectDelay = 30000,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const connectedRef = useRef(false)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  // Store callbacks in refs to avoid effect re-runs
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage
  const onConnectRef = useRef(onConnect)
  onConnectRef.current = onConnect
  const onDisconnectRef = useRef(onDisconnect)
  onDisconnectRef.current = onDisconnect

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (!mountedRef.current) return

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) {
          ws.close()
          return
        }
        connectedRef.current = true
        reconnectAttemptsRef.current = 0
        onConnectRef.current?.()
      }

      ws.onclose = () => {
        connectedRef.current = false
        wsRef.current = null
        onDisconnectRef.current?.()

        // Auto-reconnect with exponential backoff (max 5 attempts)
        if (reconnect && mountedRef.current) {
          const attempts = reconnectAttemptsRef.current
          if (attempts >= 5) {
            console.warn('[WS] 已达最大重连次数，停止重连')
            return
          }
          const delay = Math.min(
            1000 * Math.pow(2, attempts),
            maxReconnectDelay
          )
          reconnectAttemptsRef.current = attempts + 1
          console.log(
            `[WS] 将在 ${delay}ms 后重连 (第 ${attempts + 1} 次)...`
          )
          reconnectTimerRef.current = setTimeout(() => {
            if (mountedRef.current) {
              connect()
            }
          }, delay)
        }
      }

      ws.onerror = () => {
        // onerror always fires before onclose, just log
        console.warn('[WS] 连接错误')
      }

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string)
          onMessageRef.current?.(data)
        } catch {
          console.warn('[WS] 解析消息失败:', event.data)
        }
      }
    } catch (err) {
      console.error('[WS] 创建连接失败:', err)
    }
  }, [url, reconnect, maxReconnectDelay])

  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      clearReconnectTimer()
      if (wsRef.current) {
        wsRef.current.onclose = null // prevent reconnect on unmount
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect, clearReconnectTimer])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    } else {
      console.warn('[WS] 未连接，消息未发送')
    }
  }, [])

  return { send, connected: connectedRef.current }
}
