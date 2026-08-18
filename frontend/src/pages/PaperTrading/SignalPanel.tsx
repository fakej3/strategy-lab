import { cn } from '../../lib/cn'
import { fmtPrice, fmtSign, fmtPct, pnlClass } from '../../lib/format'
import type { OpenPosition } from '../../types'

interface Signal {
  strategy?: string
  signal?: string
  symbol?: string
  interval?: string
  price?: number
  ts?: string
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

  const dirColor = activePos
    ? (activePos.direction === 'long' ? 'text-green' : 'text-red')
    : (isLong ? 'text-green' : isShort ? 'text-red' : 'text-muted')

  return (
    <div className="flex flex-col h-full border-l border-border">
      <div className="px-3 py-2 border-b border-border shrink-0">
        <div className="text-xs font-semibold text-text leading-tight truncate">
          {strategy || 'Signal'}
        </div>
        {activeKey && (
          <div className="text-xs text-muted font-mono mt-0.5">
            {activeSymbol} · {activeInterval?.toUpperCase()}
          </div>
        )}
      </div>

      {/* Direction */}
      <div className="px-3 py-3 border-b border-border shrink-0">
        <div className={cn('text-lg font-bold leading-none font-mono', dirColor)}>
          {activePos
            ? activePos.direction.toUpperCase()
            : (isLong ? 'LONG' : isShort ? 'SHORT' : 'FLAT')}
        </div>
        {!activePos && signal?.signal && (
          <div className="text-xs text-muted font-mono mt-1 truncate">
            Last: {signal.signal.toUpperCase()}
          </div>
        )}
      </div>

      {/* Position details */}
      {activePos ? (
        <div className="px-3 py-3 flex flex-col gap-2 shrink-0">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted mb-0.5">Position</div>
          <Row label="Entry" value={fmtPrice(activePos.entry_price)} />
          <Row label="Size"  value={String(activePos.size)} />
          {markPrice != null && <Row label="Mark" value={fmtPrice(markPrice)} />}
          {livePnl != null && (
            <div className="mt-2 pt-2 border-t border-border">
              <div className="text-xs uppercase tracking-wider text-muted mb-1.5">Live P&L</div>
              <div className={cn('text-base font-mono font-bold tabular-nums leading-none', pnlClass(livePnl))}>
                {fmtSign(livePnl)}
              </div>
              {livePct != null && (
                <div className={cn('text-xs font-mono tabular-nums mt-0.5', pnlClass(livePct))}>
                  {fmtPct(livePct)}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="px-3 py-3 flex flex-col gap-2 shrink-0">
          {activeSymbol && markPrices[activeSymbol] != null && (
            <Row label="Market" value={fmtPrice(markPrices[activeSymbol]!)} />
          )}
          {signal?.price != null && (
            <Row label="Signal px" value={fmtPrice(signal.price)} />
          )}
          {signal?.ts && (
            <Row
              label="Signal at"
              value={new Date(signal.ts).toLocaleTimeString('en', { hour12: false })}
            />
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-muted">{label}</span>
      <span className="text-xs font-mono text-text tabular-nums">{value}</span>
    </div>
  )
}
