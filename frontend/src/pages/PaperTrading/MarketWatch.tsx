import { cn } from '../../lib/cn'
import { fmtPrice, fmtChange } from '../../lib/format'

export interface WatchItem {
  key: string      // `${symbol}|${interval}`
  symbol: string
  interval: string
  price: number
  change: number
  signal?: string
}

interface Props {
  items: WatchItem[]
  activeKey: string
  onSelect: (key: string) => void
  symbolErrors: Record<string, string>
}

export function MarketWatch({ items, activeKey, onSelect, symbolErrors }: Props) {
  return (
    <div className="flex flex-col h-full border-r border-border">
      <div className="px-3 py-2 border-b border-border shrink-0">
        <span className="section-label">Watchlist</span>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {items.map(item => {
          const isActive    = item.key === activeKey
          const hasError    = item.symbol in symbolErrors
          const changeColor = item.change > 0 ? 'text-green' : item.change < 0 ? 'text-red' : 'text-muted2'
          return (
            <button
              key={item.key}
              onClick={() => onSelect(item.key)}
              className={cn(
                'w-full px-3 py-2.5 text-left border-b border-border border-l-2 transition-colors',
                isActive
                  ? 'bg-accent-bg border-l-accent'
                  : 'hover:bg-s2 border-l-transparent',
              )}
            >
              <div className="flex items-center justify-between mb-1">
                <span className={cn(
                  'text-xs font-semibold font-mono',
                  hasError ? 'text-red/70' : isActive ? 'text-accent' : 'text-text'
                )}>
                  {item.symbol}
                </span>
                <span className="text-xs text-muted2 font-mono">{item.interval}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono tabular-nums text-text">
                  {item.price > 0 ? fmtPrice(item.price) : '—'}
                </span>
                <span className={cn('text-xs font-mono tabular-nums', changeColor)}>
                  {fmtChange(item.change)}
                </span>
              </div>
              {hasError ? (
                <div className="text-xs mt-1 font-mono text-red/60">backfill failed</div>
              ) : item.signal ? (
                <div className={cn(
                  'text-xs mt-1 font-mono uppercase font-semibold',
                  item.signal.includes('BUY') || item.signal.includes('LONG') ? 'text-green' : 'text-red'
                )}>
                  {item.signal}
                </div>
              ) : null}
            </button>
          )
        })}
      </div>
    </div>
  )
}
