import { useEffect, useRef, useCallback, useState } from 'react'
import type { BotWsMessage } from '../types'

export function useBot(onMessage: (msg: BotWsMessage) => void) {
  const wsRef    = useRef<WebSocket | null>(null)
  const retryRef = useRef(1000)
  const onMsgRef = useRef(onMessage)
  onMsgRef.current = onMessage

  const [connected, setConnected] = useState(false)

  const connect = useCallback(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/bot`)
    wsRef.current = ws

    ws.onopen = () => {
      retryRef.current = 1000
      setConnected(true)
    }
    ws.onmessage = (ev) => {
      try { onMsgRef.current(JSON.parse(ev.data) as BotWsMessage) }
      catch { /* ignore */ }
    }
    ws.onclose = (ev) => {
      setConnected(false)
      if (ev.code !== 1000) {
        setTimeout(connect, retryRef.current)
        retryRef.current = Math.min(retryRef.current * 2, 30_000)
      }
    }
    ws.onerror = () => {}
  }, [])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close(1000)
      wsRef.current = null
    }
  }, [connect])

  const send = useCallback((msg: unknown) => {
    wsRef.current?.send(JSON.stringify(msg))
  }, [])

  return { connected, send }
}
