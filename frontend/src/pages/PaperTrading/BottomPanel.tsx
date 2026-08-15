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

  return (
    <div className="flex flex-col h-full">
      <Tabs
        tabs={[
          { id: 'positions', label: 'Positions', count: positions.length },
          { id: 'fills',     label: 'Fills',     count: fills.length },
          { id: 'log',       label: 'Log' },
        ]}
        active={tab}
        onChange={setTab}
      />

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {tab === 'positions' && <PositionsTab positions={positions} markPrices={markPrices} />}
        {tab === 'fills'     && <FillsTab fills={fills} />}
        {tab === 'log'       && <LogTab messages={logMessages} />}
      </div>
    </div>
  )
}

function PositionsTab({ positions, markPrices }: { positions: OpenPosition[]; markPrices: Record<string, number> }) {
  if (positions.length === 0) {
    return <div className="text-[10px] text-muted text-center py-6">No open positions</div>
  }
  return (
    <table className="w-full text-[10px]">
      <thead>
        <tr className="border-b border-border">
          {['Symbol', 'Dir', 'Entry', 'Size', 'Mark', 'P&L', 'P&L %'].map(h => (
            <th key={h} className="px-2 py-1 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">{h}</th>
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
            <tr key={`${p.symbol}-${p.entry_price}`} className="border-b border-border/50 hover:bg-s2">
              <td className="px-2 py-1 font-mono font-semibold text-text">{p.symbol}</td>
              <td className={cn('px-2 py-1 font-semibold uppercase', p.direction === 'long' ? 'text-green' : 'text-red')}>
                {p.direction}
              </td>
              <td className="px-2 py-1 font-mono tabular-nums">{fmtPrice(p.entry_price)}</td>
              <td className="px-2 py-1 font-mono tabular-nums">{p.size}</td>
              <td className="px-2 py-1 font-mono tabular-nums">{mark != null ? fmtPrice(mark) : '—'}</td>
              <td className={cn('px-2 py-1 font-mono tabular-nums font-semibold', pnl != null ? pnlClass(pnl) : 'text-muted')}>
                {pnl != null ? fmtSign(pnl) : '—'}
              </td>
              <td className={cn('px-2 py-1 font-mono tabular-nums', pct != null ? pnlClass(pct) : 'text-muted')}>
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
  if (fills.length === 0) {
    return <div className="text-[10px] text-muted text-center py-6">No fills yet</div>
  }
  const reversed = [...fills].reverse()
  return (
    <table className="w-full text-[10px]">
      <thead>
        <tr className="border-b border-border">
          {['Time', 'Symbol', 'Side', 'Size', 'Price'].map(h => (
            <th key={h} className="px-2 py-1 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {reversed.map((f, i) => (
          <tr key={i} className="border-b border-border/50 hover:bg-s2">
            <td className="px-2 py-1 font-mono text-muted">{f.timestamp ? new Date(typeof f.timestamp === 'number' ? f.timestamp * 1000 : f.timestamp).toLocaleTimeString() : '—'}</td>
            <td className="px-2 py-1 font-mono font-semibold">{f.symbol}</td>
            <td className={cn('px-2 py-1 font-semibold uppercase', f.side.toUpperCase() === 'BUY' ? 'text-green' : 'text-red')}>
              {f.side}
            </td>
            <td className="px-2 py-1 font-mono tabular-nums">{f.size}</td>
            <td className="px-2 py-1 font-mono tabular-nums">{fmtPrice(f.fill_price)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function LogTab({ messages }: { messages: BotWsMessage[] }) {
  const lines = messages.filter(m => m.type === 'log' || m.type === 'error')
  if (lines.length === 0) {
    return <div className="text-[10px] text-muted text-center py-6">No log messages</div>
  }
  return (
    <div className="font-mono text-[10px] px-2 py-1 flex flex-col gap-0.5">
      {[...lines].reverse().map((m, i) => (
        <div key={i} className={cn('truncate', m.type === 'error' ? 'text-red' : 'text-muted2')}>
          {(m as { type: string; message: string }).message}
        </div>
      ))}
    </div>
  )
}
