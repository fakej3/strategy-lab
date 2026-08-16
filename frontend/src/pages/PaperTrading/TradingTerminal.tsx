import { useEffect, useRef, useState, useCallback } from 'react'
import { TradingChart, type ChartHandle } from './TradingChart'
import { MarketWatch, type WatchItem } from './MarketWatch'
import { SignalPanel } from './SignalPanel'
import { BottomPanel } from './BottomPanel'
import { StopModal } from './StopModal'
import { Button } from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { fmtPrice, fmtSign, fmtChange, pnlClass } from '../../lib/format'
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

  const [status,      setStatus]      = useState<BotStatus>(initialStatus)
  const [positions,   setPositions]   = useState<OpenPosition[]>(initialStatus.open_positions ?? [])
  const [fills,       setFills]       = useState<Fill[]>(initialStatus.recent_trades ?? [])
  const [markPrices,  setMarkPrices]  = useState<Record<string, number>>({})
  const [watchItems,  setWatchItems]  = useState<WatchItem[]>([])
  const [activeKey,   setActiveKey]   = useState<string>('')
  const [signal,      setSignal]      = useState<BotWsMessage & { type: 'signal' } | null>(null)
  const [allMessages, setAllMessages] = useState<BotWsMessage[]>([])
  const [fillCount,   setFillCount]   = useState(initialStatus.recent_trades?.length ?? 0)
  const [showStop,    setShowStop]    = useState(false)
  const [candlesSub,  setCandlesSub]  = useState<string>('')

  const [activeSymbol, activeInterval] = activeKey.split('|')
  const activePrice      = markPrices[activeSymbol ?? ''] ?? 0
  const activeWatchItem  = watchItems.find(w => w.key === activeKey)
  const activeChange     = activeWatchItem?.change ?? 0
  const changeColor      = activeChange > 0 ? 'text-green' : activeChange < 0 ? 'text-red' : 'text-muted'

  const totalPnl = positions.reduce((sum, p) => {
    const mark = markPrices[p.symbol]
    if (mark == null) return sum
    return sum + (p.direction === 'long'
      ? (mark - p.entry_price) * p.size
      : (p.entry_price - mark) * p.size)
  }, 0)

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
      setActiveKey(`${pairs[0].symbol}|${pairs[0].interval}`)
    }
  }, [initialStatus])

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

  useEffect(() => {
    const [sym] = activeKey.split('|')
    const pos = positions.find(p => p.symbol === sym) ?? null
    chartRef.current?.setPosition(pos)
  }, [positions, activeKey])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-3 h-10 bg-surface border-b border-border shrink-0">
        <div className="flex items-center gap-1.5">
          <span className={cn('w-1.5 h-1.5 rounded-full', connected ? 'bg-green' : 'bg-amber')} />
          <span className="text-[9px] font-semibold uppercase tracking-widest text-muted">
            {connected ? 'Live' : 'Reconnecting'}
          </span>
        </div>
        <Badge variant={status.running ? 'pass' : 'muted'}>{status.running ? 'Running' : 'Stopped'}</Badge>
        {activeKey && (
          <span className="text-[11px] font-mono font-semibold text-text">
            {activeSymbol}<span className="text-muted mx-0.5">·</span>{activeInterval?.toUpperCase()}
          </span>
        )}
        {status.strategy && (
          <span className="text-[9px] text-muted font-mono">{status.strategy}</span>
        )}

        {/* Portfolio metrics */}
        <div className="flex items-center gap-4 ml-auto">
          <Metric label="Capital"  value={`$${fmtPrice(status.capital ?? 0)}`} />
          <Metric label="Open PnL" value={fmtSign(totalPnl)}
            className={positions.length > 0 ? pnlClass(totalPnl) : 'text-muted'} />
          <Metric label="Positions" value={String(positions.length)} />
          <Metric label="Fills"     value={String(fillCount)} />
        </div>

        <Button variant="danger" size="sm" onClick={() => setShowStop(true)}>Stop</Button>
      </div>

      {/* Main 3-column body */}
      <div className="flex flex-1 min-h-0">
        {/* Left: market watch */}
        <div className="w-[130px] shrink-0 overflow-hidden">
          <MarketWatch items={watchItems} activeKey={activeKey} onSelect={setActiveKey} />
        </div>

        {/* Center: chart identity header + chart canvas */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0">
          {/* Chart header bar */}
          <div className="flex items-center gap-3 px-3 h-8 shrink-0 border-b border-border bg-surface">
            <span className="text-[13px] font-semibold font-mono text-text">
              {activeSymbol || '—'}
              <span className="text-muted mx-1">·</span>
              {activeInterval?.toUpperCase() || '—'}
            </span>
            {activePrice > 0 ? (
              <>
                <span className="text-[13px] font-mono tabular-nums text-text">{fmtPrice(activePrice)}</span>
                <span className={cn('text-[11px] font-mono tabular-nums', changeColor)}>
                  {fmtChange(activeChange)}
                </span>
              </>
            ) : (
              <span className="text-[10px] text-muted2">—</span>
            )}
          </div>

          {/* Chart + connecting overlay */}
          <div className="relative flex-1 min-h-0">
            <TradingChart ref={chartRef} className="absolute inset-0" />
            {activePrice === 0 && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
                <span className="w-2 h-2 rounded-full bg-muted animate-pulse mb-2.5" />
                <span className="text-[11px] text-muted">Connecting to market data…</span>
                <span className="text-[10px] text-muted mt-1">
                  Waiting for {activeSymbol || '…'} · {activeInterval?.toUpperCase() || '…'}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Right: signal panel */}
        <div className="w-[152px] shrink-0 overflow-hidden">
          <SignalPanel
            strategy={status.strategy ?? ''}
            activeKey={activeKey}
            signal={signal}
            positions={positions}
            markPrices={markPrices}
          />
        </div>
      </div>

      {/* Bottom panel: positions / fills / activity / log */}
      <div className="border-t border-border bg-surface shrink-0" style={{ height: '210px' }}>
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
      <span className="text-[9px] font-semibold uppercase tracking-wider text-muted">{label}</span>
      <span className={cn('text-[12px] font-mono font-semibold tabular-nums', className ?? 'text-text')}>{value}</span>
    </div>
  )
}
