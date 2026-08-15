import { cn } from '../../lib/cn'
import { fmtPrice, fmtSign, fmtPct } from '../../lib/format'
import type { OpenPosition } from '../../types'

interface Signal {
  strategy?: string
  signal?: string
  symbol?: string
  interval?: string
  price?: number
}

interface Props {
  signal: Signal | null
  positions: OpenPosition[]
  markPrices: Record<string, number>
  fillCount: number
}

export function SignalPanel({ signal, positions, markPrices, fillCount }: Props) {
  const dir = signal?.signal?.toUpperCase() ?? 'FLAT'
  const isLong  = dir.includes('BUY') || dir.includes('LONG')
  const isShort = dir.includes('SELL') || dir.includes('SHORT')

  // Find position for the signaled symbol
  const activePos = signal?.symbol
    ? positions.find(p => p.symbol === signal.symbol) ?? null
    : positions[0] ?? null

  const markPrice = activePos ? (markPrices[activePos.symbol] ?? null) : null

  let livePnl: number | null = null
  let livePct: number | null = null
  if (activePos && markPrice != null) {
    livePnl = activePos.direction === 'long'
      ? (markPrice - activePos.entry_price) * activePos.size
      : (activePos.entry_price - markPrice) * activePos.size
    livePct = (livePnl / (activePos.entry_price * activePos.size)) * 100
  }

  return (
    <div className="flex flex-col h-full border-b border-border">
      <div className="px-3 py-2 border-b border-border">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-muted">
          {signal?.strategy ?? 'Signal'}
        </span>
      </div>

      <div className="px-3 py-3 border-b border-border">
        <div className={cn('text-[22px] font-bold leading-none mb-1',
          isLong ? 'text-green' : isShort ? 'text-red' : 'text-muted')}>
          {isLong ? 'LONG' : isShort ? 'SHORT' : 'FLAT'}
        </div>
        {signal?.symbol && (
          <div className="text-[10px] text-muted font-mono">
            {signal.symbol}{signal.interval ? ` · ${signal.interval}` : ''}
          </div>
        )}
      </div>

      <div className="px-3 py-2 border-b border-border flex flex-col gap-1.5">
        {signal?.price != null && (
          <Row label="Mark Price" value={fmtPrice(signal.price)} mono />
        )}
        <Row label="Positions" value={String(positions.length)} />
        <Row label="Fills" value={String(fillCount)} />
      </div>

      {activePos && (
        <div className="px-3 py-2 border-b border-border bg-s2">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-muted mb-1.5">Open Position</div>
          <Row label="Symbol"  value={activePos.symbol} mono />
          <Row label="Entry"   value={fmtPrice(activePos.entry_price)} mono />
          <Row label="Size"    value={String(activePos.size)} mono />
          {livePnl != null && (
            <div className="flex items-center justify-between mt-1">
              <span className="text-[9px] text-muted uppercase tracking-wider">P&L</span>
              <span className={cn('text-[11px] font-mono font-semibold tabular-nums', livePnl >= 0 ? 'text-green' : 'text-red')}>
                {fmtSign(livePnl)} ({fmtPct(livePct)})
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[9px] text-muted uppercase tracking-wider">{label}</span>
      <span className={cn('text-[10px] text-text tabular-nums', mono && 'font-mono')}>{value}</span>
    </div>
  )
}
