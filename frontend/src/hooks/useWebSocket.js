import { useRef, useState, useCallback } from 'react'

export default function useWebSocket(url) {
  const wsRef = useRef(null)
  const callbackRef = useRef(null)
  const connectedRef = useRef(false)
  const [isConnected, setIsConnected] = useState(false)
  const [lastError, setLastError] = useState(null)
  const reconnectRef = useRef(null)
  const heartbeatRef = useRef(null)
  const pendingMessagesRef = useRef([])

  const cleanup = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current)
      heartbeatRef.current = null
    }
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current)
      reconnectRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    cleanup()

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      connectedRef.current = true
      setIsConnected(true)
      setLastError(null)

      const pending = pendingMessagesRef.current
      pendingMessagesRef.current = []
      for (const msg of pending) {
        ws.send(JSON.stringify(msg))
      }

      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (callbackRef.current) {
          callbackRef.current(data)
        }
      } catch (e) {
        console.warn('Failed to parse WS message:', e)
      }
    }

    ws.onerror = () => {
      setLastError('WebSocket connection error')
    }

    ws.onclose = (event) => {
      connectedRef.current = false
      setIsConnected(false)
      cleanup()
      if (!event.wasClean) {
        reconnectRef.current = setTimeout(() => {
          connect()
        }, 3000)
      }
    }
  }, [url, cleanup])

  const disconnect = useCallback(() => {
    cleanup()
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect')
      wsRef.current = null
    }
    connectedRef.current = false
    setIsConnected(false)
  }, [cleanup])

  const sendMessage = useCallback((message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    } else {
      pendingMessagesRef.current.push(message)
    }
  }, [])

  const onMessage = useCallback((callback) => {
    callbackRef.current = callback
  }, [])

  return { connect, disconnect, sendMessage, isConnected, onMessage, lastError }
}
