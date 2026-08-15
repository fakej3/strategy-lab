import { useEffect, useRef, useCallback } from 'react'
import type { JobWsMessage } from '../types'

export function useJobWS(
  jobId: string,
  onMessage: (msg: JobWsMessage) => void,
  active: boolean,
) {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(1000)
  const onMsgRef = useRef(onMessage)
  onMsgRef.current = onMessage

  const connect = useCallback(() => {
    if (!active) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/job/${jobId}`)
    wsRef.current = ws

    ws.onopen = () => { retryRef.current = 1000 }
    ws.onmessage = (ev) => {
      try { onMsgRef.current(JSON.parse(ev.data) as JobWsMessage) }
      catch { /* ignore parse errors */ }
    }
    ws.onclose = (ev) => {
      if (ev.code !== 1000 && active) {
        setTimeout(connect, retryRef.current)
        retryRef.current = Math.min(retryRef.current * 2, 30_000)
      }
    }
    ws.onerror = () => {}
  }, [jobId, active])

  useEffect(() => {
    if (!active) return
    connect()
    return () => {
      wsRef.current?.close(1000)
      wsRef.current = null
    }
  }, [active, connect])
}
