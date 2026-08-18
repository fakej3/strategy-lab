import { useState } from 'react'
import { cn } from '../../lib/cn'
import { fmtPrice, fmtSign, fmtPct, pnlClass } from '../../lib/format'
import { Tabs } from '../../components/ui/Tabs'
import type { OpenPosition, Fill, BotWsMessage } from '../../types'

interface Props {
  positions: OpenPosition[]
  fills: Fill[]
  logMessages: BotWsMessage[]
  markPrices: Record<string, number>
}

export function BottomPanel({ positions, fills, logMessages, markPrices }: Props) {
  const [tab, setTab] = useState('positions')

  const activityCount = logMessages.filter(m =>
    m.type === 'signal' || m.type === 'fill' || m.type === 'order' || m.type === 'error'
  ).length

  return (
    <div className="flex flex-col h-full">
      <Tabs
        tabs={[
          { id: 'positions', label: 'Positions', count: positions.length },
          { id: 'fills',     label: 'Fills',     count: fills.length },
          { id: 'activity',  label: 'Activity',  count: activityCount },
          { id: 'log',       label: 'Log' },
        ]}
        active={tab}
        onChange={setTab}
      />

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {tab === 'positions' && <PositionsTab positions={positions} markPrices={markPrices} />}
        {tab === 'fills'     && <FillsTab fills={fills} />}
        {tab === 'activity'  && <ActivityTab messages={logMessages} />}
        {tab === 'log'       && <LogTab messages={logMessages} />}
      </div>
    </div>
  )
}

function EmptyRow({ message }: { message: string }) {
  return <div className="text-xs text-muted text-center py-6 font-mono">{message}</div>
}

function PositionsTab({ positions, markPrices }: { positions: OpenPosition[]; markPrices: Record<string, number> }) {
  if (positions.length === 0) return <EmptyRow message="No open positions" />
  return (
    <table className="w-full">
      <thead>
        <tr className="border-b border-border">
          {['Symbol', 'Dir', 'Entry', 'Size', 'Mark', 'P&L', 'P&L %'].map(h => (
            <th key={h} className="px-3 py-1.5 text-left text-xs font-medium text-muted">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {positions.map(p => {
          const mark = markPrices[p.symbol] ?? null
          let pnl: number | null = null
          let pct: number | null = null
          if (mark != null) {
            pnl = p.direction === 'long'
              ? (mark - p.entry_price) * p.size
              : (p.entry_price - mark) * p.size
            pct = (pnl / (p.entry_price * p.size)) * 100
          }
          return (
            <tr key={`${p.symbol}-${p.entry_price}`} className="border-b border-border/40 hover:bg-s2">
              <td className="px-3 py-1.5 font-mono text-sm font-semibold text-text">{p.symbol}</td>
              <td className={cn('px-3 py-1.5 text-xs font-bold uppercase', p.direction === 'long' ? 'text-green' : 'text-red')}>
                {p.direction}
              </td>
              <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-muted">{fmtPrice(p.entry_price)}</td>
              <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-muted">{p.size}</td>
              <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-text">{mark != null ? fmtPrice(mark) : '—'}</td>
              <td className={cn('px-3 py-1.5 font-mono text-xs tabular-nums font-semibold', pnl != null ? pnlClass(pnl) : 'text-muted')}>
                {pnl != null ? fmtSign(pnl) : '—'}
              </td>
              <td className={cn('px-3 py-1.5 font-mono text-xs tabular-nums', pct != null ? pnlClass(pct) : 'text-muted')}>
                {pct != null ? fmtPct(pct) : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function FillsTab({ fills }: { fills: Fill[] }) {
  if (fills.length === 0) return <EmptyRow message="No fills yet" />
  const reversed = [...fills].reverse()
  return (
    <table className="w-full">
      <thead>
        <tr className="border-b border-border">
          {['Time', 'Symbol', 'Side', 'Size', 'Price'].map(h => (
            <th key={h} className="px-3 py-1.5 text-left text-xs font-medium text-muted">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {reversed.map((f, i) => (
          <tr key={i} className="border-b border-border/40 hover:bg-s2">
            <td className="px-3 py-1.5 font-mono text-xs text-muted">
              {f.timestamp ? new Date(typeof f.timestamp === 'number' ? f.timestamp * 1000 : f.timestamp).toLocaleTimeString() : '—'}
            </td>
            <td className="px-3 py-1.5 font-mono text-xs font-semibold text-text">{f.symbol}</td>
            <td className={cn('px-3 py-1.5 text-xs font-bold uppercase', f.side.toUpperCase() === 'BUY' ? 'text-green' : 'text-red')}>
              {f.side}
            </td>
            <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-muted">{f.size}</td>
            <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-text">{fmtPrice(f.fill_price)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function fmtTs(ts: string | undefined): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString('en', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function ActivityTab({ messages }: { messages: BotWsMessage[] }) {
  const entries: Array<{ id: number; time: string; label: string; detail: string; color: string }> = []
  let id = 0

  for (const msg of messages) {
    switch (msg.type) {
      case 'signal': {
        const dir    = msg.signal.toUpperCase()
        const isLong = dir.includes('BUY') || dir.includes('LONG')
        entries.push({
          id:     id++,
          time:   fmtTs(msg.ts),
          label:  'SIG',
          detail: `${msg.signal.toUpperCase()}  ${msg.symbol}·${msg.interval}${msg.price != null ? `  @ ${fmtPrice(msg.price)}` : ''}`,
          color:  isLong ? 'text-green' : 'text-red',
        })
        break
      }
      case 'fill':
        entries.push({
          id:     id++,
          time:   fmtTs(msg.ts),
          label:  'FILL',
          detail: `${msg.side.toUpperCase()}  ${msg.size} @ ${fmtPrice(msg.fill_price)}  ${msg.symbol}`,
          color:  msg.side.toUpperCase() === 'BUY' ? 'text-green' : 'text-red',
        })
        break
      case 'order':
        entries.push({
          id:     id++,
          time:   fmtTs(msg.ts),
          label:  'ORD',
          detail: `${(msg.side ?? '').toUpperCase()}  ${msg.order_id ?? ''}`,
          color:  'text-accent',
        })
        break
      case 'error':
        entries.push({
          id:     id++,
          time:   fmtTs(msg.ts),
          label:  'ERR',
          detail: (msg as { type: string; message: string }).message,
          color:  'text-red',
        })
        break
    }
  }

  if (entries.length === 0) return <EmptyRow message="No activity yet" />

  return (
    <div className="font-mono text-xs px-3 py-2">
      {[...entries].reverse().map(e => (
        <div key={e.id} className="flex items-baseline gap-2.5 py-0.5 border-b border-border/20 last:border-0">
          {e.time && <span className="text-muted2 shrink-0 tabular-nums">{e.time}</span>}
          <span className={cn('shrink-0 font-bold w-8', e.color)}>{e.label}</span>
          <span className={cn('truncate', e.color)}>{e.detail}</span>
        </div>
      ))}
    </div>
  )
}

function LogTab({ messages }: { messages: BotWsMessage[] }) {
  const lines = messages.filter(m => m.type === 'log' || m.type === 'error')
  if (lines.length === 0) return <EmptyRow message="No log messages" />
  return (
    <div className="font-mono text-xs px-3 py-2 flex flex-col gap-0.5">
      {[...lines].reverse().map((m, i) => (
        <div key={i} className={cn('truncate', m.type === 'error' ? 'text-red' : 'text-muted2')}>
          {(m as { type: string; message: string }).message}
        </div>
      ))}
    </div>
  )
}
