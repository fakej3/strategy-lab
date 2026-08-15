import { useEffect, useState } from 'react'
import { botApi } from '../../api/bot'
import { StoppedState } from './StoppedState'
import { TradingTerminal } from './TradingTerminal'
import { LoadingState } from '../../components/ui/EmptyState'
import type { BotStatus, AvailableStrategy } from '../../types'

export function PaperTrading() {
  const [status,     setStatus]     = useState<BotStatus | null>(null)
  const [strategies, setStrategies] = useState<AvailableStrategy[]>([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')

  async function load() {
    setLoading(true)
    try {
      const [st, strats] = await Promise.all([
        botApi.status(),
        botApi.availableStrategies(),
      ])
      setStatus(st)
      setStrategies(strats)
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  if (loading) return <LoadingState />

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-red text-[12px]">Failed to load bot status: {error}</div>
      </div>
    )
  }

  if (!status?.running) {
    return (
      <StoppedState
        strategies={strategies}
        error={error || undefined}
        onStarted={load}
      />
    )
  }

  return (
    <TradingTerminal
      initialStatus={status}
      onStopped={load}
    />
  )
}
