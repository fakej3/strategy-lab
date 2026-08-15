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
}

export function MarketWatch({ items, activeKey, onSelect }: Props) {
  return (
    <div className="flex flex-col h-full border-r border-border">
      <div className="px-2.5 py-1.5 border-b border-border shrink-0">
        <span className="section-label">Market Watch</span>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {items.map(item => {
          const isActive = item.key === activeKey
          const isPos    = item.change >= 0
          return (
            <button
              key={item.key}
              onClick={() => onSelect(item.key)}
              className={cn(
                'w-full px-2.5 py-2 text-left border-b border-border border-l-2 transition-colors',
                isActive
                  ? 'bg-accent-bg border-l-accent'
                  : 'hover:bg-s2 border-l-transparent',
              )}
            >
              <div className="flex items-center justify-between mb-0.5">
                <span className={cn('text-[10px] font-semibold font-mono', isActive ? 'text-accent' : 'text-text')}>
                  {item.symbol}
                </span>
                <span className="text-[8px] text-muted">{item.interval}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-mono tabular-nums text-text">
                  {item.price > 0 ? fmtPrice(item.price) : '—'}
                </span>
                <span className={cn('text-[9px] font-mono tabular-nums', isPos ? 'text-green' : 'text-red')}>
                  {fmtChange(item.change)}
                </span>
              </div>
              {item.signal && (
                <div className={cn('text-[8px] mt-0.5 font-mono uppercase',
                  item.signal.includes('BUY') || item.signal.includes('LONG') ? 'text-green' : 'text-red')}>
                  {item.signal}
                </div>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
