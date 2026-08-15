import { useEffect, useRef, useState, useCallback } from 'react'
import { TradingChart, type ChartHandle } from './TradingChart'
import { MarketWatch, type WatchItem } from './MarketWatch'
import { SignalPanel } from './SignalPanel'
import { ActivityFeed } from './ActivityFeed'
import { BottomPanel } from './BottomPanel'
import { StopModal } from './StopModal'
import { Button } from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { fmtPrice, fmtSign, pnlClass } from '../../lib/format'
import { cn } from '../../lib/cn'
import { botApi } from '../../api/bot'
import { useBot } from '../../hooks/useBot'
import type { BotStatus, OpenPosition, Fill, BotWsMessage, Candle } from '../../types'

interface Props {
  initialStatus: BotStatus
  onStopped: () => void
}

export function TradingTerminal({ initialStatus, onStopped }: Props) {
  const chartRef = useRef<ChartHandle>(null)

  const [status,     setStatus]     = useState<BotStatus>(initialStatus)
  const [positions,  setPositions]  = useState<OpenPosition[]>(initialStatus.open_positions ?? [])
  const [fills,      setFills]      = useState<Fill[]>(initialStatus.recent_trades ?? [])
  const [markPrices, setMarkPrices] = useState<Record<string, number>>({})
  const [watchItems, setWatchItems] = useState<WatchItem[]>([])
  const [activeKey,  setActiveKey]  = useState<string>('')
  const [signal,     setSignal]     = useState<BotWsMessage & { type: 'signal' } | null>(null)
  const [allMessages, setAllMessages] = useState<BotWsMessage[]>([])
  const [fillCount,   setFillCount]   = useState(initialStatus.recent_trades?.length ?? 0)
  const [showStop, setShowStop]       = useState(false)
  const [candlesSub, setCandlesSub]   = useState<string>('')

  // Derived totals
  const totalPnl = positions.reduce((sum, p) => {
    const mark = markPrices[p.symbol]
    if (mark == null) return sum
    return sum + (p.direction === 'long'
      ? (mark - p.entry_price) * p.size
      : (p.entry_price - mark) * p.size)
  }, 0)

  // Build watchlist from status pairs
  useEffect(() => {
    const pairs = initialStatus.symbols?.flatMap(sym =>
      (initialStatus.intervals ?? []).map(iv => ({ symbol: sym, interval: iv }))
    ) ?? []
    setWatchItems(pairs.map(({ symbol, interval }) => ({
      key: `${symbol}|${interval}`,
      symbol,
      interval,
      price: 0,
      change: 0,
    })))
    if (pairs.length > 0) {
      const first = `${pairs[0].symbol}|${pairs[0].interval}`
      setActiveKey(first)
    }
  }, [initialStatus])

  // Load initial candles when active pair changes
  useEffect(() => {
    if (!activeKey) return
    const [sym, iv] = activeKey.split('|')
    if (!sym || !iv) return
    setCandlesSub(activeKey)
    botApi.candles(sym, iv).then((candles: Candle[]) => {
      chartRef.current?.setData(candles)
      chartRef.current?.fitContent()
    }).catch(() => {})
  }, [activeKey])

  const handleWsMessage = useCallback((msg: BotWsMessage) => {
    setAllMessages(prev => [...prev.slice(-500), msg])

    switch (msg.type) {
      case 'candle': {
        const key = `${msg.symbol}|${msg.interval}`
        if (key === candlesSub) {
          chartRef.current?.updateCandle(msg)
        }
        setMarkPrices(prev => ({ ...prev, [msg.symbol]: msg.close }))
        setWatchItems(prev => prev.map(w =>
          w.symbol === msg.symbol && w.interval === msg.interval
            ? { ...w, price: msg.close, change: msg.close - msg.open }
            : w
        ))
        break
      }
      case 'signal': {
        const key = `${msg.symbol}|${msg.interval}`
        if (key === candlesSub) {
          chartRef.current?.addSignal(msg)
        }
        setSignal(msg)
        setWatchItems(prev => prev.map(w =>
          w.symbol === msg.symbol && w.interval === msg.interval
            ? { ...w, signal: msg.signal }
            : w
        ))
        break
      }
      case 'fill': {
        chartRef.current?.addFill(msg)
        setFillCount(n => n + 1)
        setFills(prev => [...prev, {
          symbol:     msg.symbol,
          side:       msg.side,
          size:       msg.size,
          fill_price: msg.fill_price,
          timestamp:  Math.floor(Date.now() / 1000),
        }])
        break
      }
      case 'status': {
        const st = msg as unknown as BotStatus
        setStatus(st)
        setPositions(st.open_positions ?? [])
        break
      }
    }
  }, [candlesSub])

  const { connected } = useBot(handleWsMessage)

  // Sync entry line when position changes for active symbol
  useEffect(() => {
    const [sym] = activeKey.split('|')
    const pos = positions.find(p => p.symbol === sym) ?? null
    chartRef.current?.setPosition(pos)
  }, [positions, activeKey])

  const totalEquity = status.capital ?? 0
  const totalValue  = totalEquity + totalPnl

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-surface border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className={cn('w-2 h-2 rounded-full', connected ? 'bg-green' : 'bg-amber')} />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-muted">
            {connected ? 'Live' : 'Reconnecting…'}
          </span>
        </div>
        <Badge variant={status.running ? 'pass' : 'muted'}>{status.running ? 'Running' : 'Stopped'}</Badge>
        {status.strategy && (
          <span className="text-[10px] text-muted font-mono">{status.strategy}</span>
        )}

        {/* Portfolio metrics */}
        <div className="flex items-center gap-4 ml-auto">
          <Metric label="Capital" value={`$${fmtPrice(totalEquity)}`} />
          <Metric label="Open PnL" value={fmtSign(totalPnl)}
            className={positions.length > 0 ? pnlClass(totalPnl) : 'text-muted'} />
          <Metric label="Equity" value={`$${fmtPrice(totalValue)}`} />
          <Metric label="Positions" value={String(positions.length)} />
          <Metric label="Fills" value={String(fillCount)} />
        </div>

        <Button variant="danger" size="xs" onClick={() => setShowStop(true)}>■ Stop</Button>
      </div>

      {/* Main 3-column body */}
      <div className="flex flex-1 min-h-0">
        {/* Left: market watch */}
        <div className="w-36 shrink-0 border-r border-border overflow-hidden">
          <MarketWatch items={watchItems} activeKey={activeKey} onSelect={setActiveKey} />
        </div>

        {/* Center: chart + activity feed */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* Chart takes ~70% height */}
          <div className="flex min-h-0" style={{ flex: '7 1 0' }}>
            <TradingChart ref={chartRef} className="flex-1" />
          </div>

          {/* Activity feed below chart */}
          <div className="border-t border-border" style={{ flex: '3 1 0', minHeight: 0 }}>
            <ActivityFeed messages={allMessages} />
          </div>
        </div>

        {/* Right: signal panel */}
        <div className="w-44 shrink-0 border-l border-border overflow-hidden">
          <SignalPanel
            signal={signal}
            positions={positions}
            markPrices={markPrices}
            fillCount={fillCount}
          />
        </div>
      </div>

      {/* Bottom panel: positions / fills / log */}
      <div className="border-t border-border bg-surface shrink-0" style={{ height: '200px' }}>
        <BottomPanel
          positions={positions}
          fills={fills}
          logMessages={allMessages}
          markPrices={markPrices}
        />
      </div>

      {showStop && (
        <StopModal
          onClose={() => setShowStop(false)}
          onStopped={() => { setShowStop(false); onStopped() }}
        />
      )}
    </div>
  )
}

function Metric({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-[8px] font-semibold uppercase tracking-wider text-muted">{label}</span>
      <span className={cn('text-[11px] font-mono font-semibold tabular-nums', className ?? 'text-text')}>{value}</span>
    </div>
  )
}
