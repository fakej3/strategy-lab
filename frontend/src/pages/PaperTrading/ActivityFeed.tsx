import { useState } from 'react'
import { cn } from '../../lib/cn'
import { fmtPrice } from '../../lib/format'
import type { BotWsMessage } from '../../types'

type FilterKey = 'ALL' | 'SIGNALS' | 'FILLS' | 'ORDERS' | 'ERRORS'

interface FeedEntry {
  id: number
  type: FilterKey
  ts: string
  text: string
  color: string
}

let idSeq = 0

function toEntry(msg: BotWsMessage): FeedEntry | null {
  const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
  switch (msg.type) {
    case 'signal': {
      const dir = msg.signal.toUpperCase()
      const isLong = dir.includes('BUY') || dir.includes('LONG')
      return { id: idSeq++, type: 'SIGNALS', ts, color: isLong ? 'text-green' : 'text-red',
        text: `${msg.signal.toUpperCase()}  ${msg.symbol}  ${msg.interval}` }
    }
    case 'fill':
      return { id: idSeq++, type: 'FILLS', ts, color: msg.side.toUpperCase() === 'BUY' ? 'text-green' : 'text-red',
        text: `FILL ${msg.side.toUpperCase()} ${msg.size} @ ${fmtPrice(msg.fill_price)}  (${msg.symbol})` }
    case 'order':
      return { id: idSeq++, type: 'ORDERS', ts, color: 'text-accent',
        text: `ORDER ${msg.side?.toUpperCase() ?? '?'} ${msg.order_id ?? ''}` }
    case 'error':
      return { id: idSeq++, type: 'ERRORS', ts, color: 'text-red',
        text: `ERROR  ${msg.message}` }
    default:
      return null
  }
}

interface Props {
  messages: BotWsMessage[]
}

export function ActivityFeed({ messages }: Props) {
  const [filter, setFilter] = useState<FilterKey>('ALL')

  const entries: FeedEntry[] = []
  for (const m of messages) {
    const e = toEntry(m)
    if (e) entries.push(e)
  }

  const visible = filter === 'ALL' ? entries : entries.filter(e => e.type === filter)
  const reversed = [...visible].reverse()

  const filters: FilterKey[] = ['ALL', 'SIGNALS', 'FILLS', 'ORDERS', 'ERRORS']

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-border shrink-0">
        {filters.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'px-2 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider transition-colors',
              filter === f
                ? 'bg-accent/15 text-accent'
                : 'text-muted hover:text-text',
            )}
          >
            {f}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin font-mono text-[10px] px-2 py-1 flex flex-col-reverse">
        {reversed.length === 0 && (
          <div className="text-muted text-center py-4">No activity yet</div>
        )}
        {reversed.map(e => (
          <div key={e.id} className="flex gap-2 py-0.5 border-b border-border/30 last:border-0">
            <span className="text-muted shrink-0">{e.ts}</span>
            <span className={cn('truncate', e.color)}>{e.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
