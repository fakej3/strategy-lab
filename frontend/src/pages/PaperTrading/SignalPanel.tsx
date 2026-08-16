import { cn } from '../../lib/cn'
import { fmtPrice, fmtSign, fmtPct, pnlClass } from '../../lib/format'
import type { OpenPosition } from '../../types'

interface Signal {
  strategy?: string
  signal?: string
  symbol?: string
  interval?: string
  price?: number
}

interface Props {
  strategy: string
  activeKey: string
  signal: Signal | null
  positions: OpenPosition[]
  markPrices: Record<string, number>
}

export function SignalPanel({ strategy, activeKey, signal, positions, markPrices }: Props) {
  const [activeSymbol, activeInterval] = activeKey.split('|')

  const dir     = signal?.signal?.toUpperCase() ?? ''
  const isLong  = dir.includes('BUY') || dir.includes('LONG')
  const isShort = dir.includes('SELL') || dir.includes('SHORT')

  const activePos = activeSymbol
    ? positions.find(p => p.symbol === activeSymbol) ?? null
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
      {/* Header: strategy name + instrument */}
      <div className="px-2.5 py-2 border-b border-border shrink-0">
        <div className="text-[11px] font-semibold text-text leading-tight truncate">
          {strategy || 'Signal'}
        </div>
        {activeKey && (
          <div className="text-[9px] text-muted font-mono mt-0.5">
            {activeSymbol} · {activeInterval?.toUpperCase()}
          </div>
        )}
      </div>

      {/* Direction indicator */}
      <div className="px-2.5 py-2.5 border-b border-border shrink-0">
        <div className={cn('text-[15px] font-bold leading-none font-mono',
          activePos
            ? (activePos.direction === 'long' ? 'text-green' : 'text-red')
            : (isLong ? 'text-green' : isShort ? 'text-red' : 'text-muted'))}>
          {activePos
            ? activePos.direction.toUpperCase()
            : (isLong ? 'LONG' : isShort ? 'SHORT' : 'FLAT')}
        </div>
        {!activePos && signal?.signal && (
          <div className="text-[9px] text-muted font-mono mt-1 truncate">
            Last: {signal.signal.toUpperCase()}
          </div>
        )}
      </div>

      {/* Position details when open */}
      {activePos ? (
        <div className="px-2.5 py-2.5 flex flex-col gap-1.5 shrink-0">
          <div className="text-[8px] font-semibold uppercase tracking-wider text-muted mb-0.5">Position</div>
          <Row label="Entry" value={fmtPrice(activePos.entry_price)} mono />
          <Row label="Size"  value={String(activePos.size)} mono />
          {markPrice != null && <Row label="Mark" value={fmtPrice(markPrice)} mono />}
          {livePnl != null && (
            <div className="mt-1.5 pt-1.5 border-t border-border/60">
              <div className="text-[8px] uppercase tracking-wider text-muted mb-1">Live P&L</div>
              <div className={cn('text-[14px] font-mono font-bold tabular-nums leading-none', pnlClass(livePnl))}>
                {fmtSign(livePnl)}
              </div>
              {livePct != null && (
                <div className={cn('text-[10px] font-mono tabular-nums mt-0.5', pnlClass(livePct))}>
                  {fmtPct(livePct)}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Flat: show last signal price if available */
        signal?.price != null && (
          <div className="px-2.5 py-2.5 shrink-0">
            <Row label="Signal px" value={fmtPrice(signal.price)} mono />
          </div>
        )
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
