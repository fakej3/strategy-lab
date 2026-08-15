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
    <div className="flex flex-col h-full border-l border-border">
      <div className="px-2.5 py-1.5 border-b border-border shrink-0">
        <span className="section-label">{signal?.strategy ?? 'Signal'}</span>
      </div>

      {/* Direction indicator */}
      <div className="px-2.5 py-2 border-b border-border shrink-0">
        <div className={cn('text-[16px] font-bold leading-none font-mono mb-0.5',
          isLong ? 'text-green' : isShort ? 'text-red' : 'text-muted')}>
          {isLong ? 'LONG' : isShort ? 'SHORT' : 'FLAT'}
        </div>
        {signal?.symbol && (
          <div className="text-[9px] text-muted font-mono">
            {signal.symbol}{signal.interval ? ` · ${signal.interval}` : ''}
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="px-2.5 py-2 border-b border-border flex flex-col gap-1 shrink-0">
        {signal?.price != null && <Row label="Mark" value={fmtPrice(signal.price)} mono />}
        <Row label="Positions" value={String(positions.length)} />
        <Row label="Fills"     value={String(fillCount)} />
      </div>

      {/* Open position */}
      {activePos && (
        <div className="px-2.5 py-2 border-b border-border bg-s2 flex flex-col gap-1 shrink-0">
          <div className="section-label mb-0.5">Open Position</div>
          <Row label="Symbol" value={activePos.symbol} mono />
          <Row label="Entry"  value={fmtPrice(activePos.entry_price)} mono />
          <Row label="Size"   value={String(activePos.size)} mono />
          {livePnl != null && (
            <div className="flex items-center justify-between mt-0.5">
              <span className="text-[9px] text-muted uppercase tracking-wider">P&L</span>
              <span className={cn('text-[10px] font-mono font-semibold tabular-nums', livePnl >= 0 ? 'text-green' : 'text-red')}>
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
      <span className="text-[8px] text-muted uppercase tracking-wider">{label}</span>
      <span className={cn('text-[10px] text-text tabular-nums', mono && 'font-mono')}>{value}</span>
    </div>
  )
}
