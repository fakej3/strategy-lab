import { useEffect, useState } from 'react'
import { botApi } from '../../api/bot'
import { Sentinel } from './Sentinel'
import { LoadingState } from '../../components/ui/EmptyState'
import type { AvailableStrategy } from '../../types'

export function PaperTrading() {
  const [strategies, setStrategies] = useState<AvailableStrategy[]>([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')

  useEffect(() => {
    botApi.availableStrategies()
      .then(s => setStrategies(s))
      .catch(ex => setError(ex instanceof Error ? ex.message : String(ex)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingState />

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-red text-[12px]">Failed to load strategies: {error}</div>
      </div>
    )
  }

  return <Sentinel strategies={strategies} />
}
