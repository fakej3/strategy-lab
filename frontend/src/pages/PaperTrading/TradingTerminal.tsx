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

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']

interface Props {
  initialStatus: BotStatus
  onStopped: () => void
}

export function TradingTerminal({ initialStatus, onStopped }: Props) {
  const chartRef = useRef<ChartHandle>(null)

  const [status,      setStatus]      = useState<BotStatus>(initialStatus)
  const [positions,   setPositions]   = useState<OpenPosition[]>(initialStatus.open_positions ?? [])
  const [fills,       setFills]       = useState<Fill[]>(initialStatus.recent_trades ?? [])
  const [markPrices,  setMarkPrices]  = useState<Record<string, number>>(initialStatus.mark_prices ?? {})
  const [watchItems,  setWatchItems]  = useState<WatchItem[]>([])
  const [activeKey,   setActiveKey]   = useState<string>('')
  const [signal,      setSignal]      = useState<BotWsMessage & { type: 'signal' } | null>(null)
  const [allMessages, setAllMessages] = useState<BotWsMessage[]>([])
  const [fillCount,   setFillCount]   = useState(initialStatus.recent_trades?.length ?? 0)
  const [showStop,    setShowStop]    = useState(false)
  const [candlesSub,  setCandlesSub]  = useState<string>('')

  const [hasHistoricalData, setHasHistoricalData] = useState(false)
  const [isLoadingHistory,  setIsLoadingHistory]  = useState(false)
  const [historyError,      setHistoryError]      = useState<string | null>(null)
  const [symbolErrors,      setSymbolErrors]      = useState<Record<string, string>>({})
  const [historyLoadKey,    setHistoryLoadKey]    = useState(0)

  const [pendingInterval, setPendingInterval] = useState<string | null>(null)
  const [isSwitching,     setIsSwitching]     = useState(false)

  const [activeSymbol, activeInterval] = activeKey.split('|')
  const activePrice     = markPrices[activeSymbol ?? ''] ?? 0
  const activeWatchItem = watchItems.find(w => w.key === activeKey)
  const activeChange    = activeWatchItem?.change ?? 0
  const changeColor     = activeChange > 0 ? 'text-green' : activeChange < 0 ? 'text-red' : 'text-muted'

  const totalPnl = positions.reduce((sum, p) => {
    const mark = markPrices[p.symbol]
    if (mark == null) return sum
    return sum + (p.direction === 'long'
      ? (mark - p.entry_price) * p.size
      : (p.entry_price - mark) * p.size)
  }, 0)

  const hasHistoricalDataRef = useRef(false)
  const statusRef            = useRef(status)
  const markPricesRef        = useRef(markPrices)
  useEffect(() => { statusRef.current = status }, [status])
  useEffect(() => { markPricesRef.current = markPrices }, [markPrices])
  useEffect(() => { hasHistoricalDataRef.current = hasHistoricalData }, [hasHistoricalData])

  useEffect(() => {
    const pairs = initialStatus.symbols?.flatMap(sym =>
      (initialStatus.intervals ?? []).map(iv => ({ symbol: sym, interval: iv }))
    ) ?? []
    setWatchItems(pairs.map(({ symbol, interval }) => ({
      key:      `${symbol}|${interval}`,
      symbol,
      interval,
      price:    initialStatus.mark_prices?.[symbol] ?? 0,
      change:   0,
    })))
    if (pairs.length > 0) {
      setActiveKey(`${pairs[0].symbol}|${pairs[0].interval}`)
    }
  }, [initialStatus])

  useEffect(() => {
    if (!activeKey) return
    const [sym, iv] = activeKey.split('|')
    if (!sym || !iv) return

    let cancelled = false
    setHasHistoricalData(false)
    hasHistoricalDataRef.current = false
    setIsLoadingHistory(true)
    setHistoryError(null)
    setCandlesSub(activeKey)

    botApi.setActivePair(sym, iv).catch(() => {})

    botApi.candles(sym, iv).then((candles: Candle[]) => {
      if (cancelled) return
      chartRef.current?.setData(candles)
      chartRef.current?.fitContent()
      if (candles.length > 0) {
        const last = candles[candles.length - 1]
        setMarkPrices(prev => ({ ...prev, [sym]: last.close }))
        setHasHistoricalData(true)
        hasHistoricalDataRef.current = true
      }
      setIsLoadingHistory(false)
    }).catch((err: unknown) => {
      if (cancelled) return
      setHistoryError(err instanceof Error ? err.message : 'Failed to load history')
      setIsLoadingHistory(false)
    })

    return () => { cancelled = true }
  }, [activeKey, historyLoadKey])

  const handleWsMessage = useCallback((msg: BotWsMessage) => {
    setAllMessages(prev => [...prev.slice(-500), msg])

    switch (msg.type) {
      case 'candle': {
        const key = `${msg.symbol}|${msg.interval}`
        if (key === candlesSub) chartRef.current?.updateCandle(msg)
        setMarkPrices(prev => ({ ...prev, [msg.symbol]: msg.close }))
        setWatchItems(prev => prev.map(w =>
          w.symbol === msg.symbol && w.interval === msg.interval
            ? { ...w, price: msg.close, change: msg.open > 0 ? ((msg.close - msg.open) / msg.open) * 100 : 0 }
            : w
        ))
        break
      }
      case 'signal': {
        const key = `${msg.symbol}|${msg.interval}`
        if (key === candlesSub) chartRef.current?.addSignal(msg)
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
      case 'error': {
        const m = msg.message?.match(/^Backfill failed: ([A-Z0-9]+)\//)
        if (m?.[1]) setSymbolErrors(prev => ({ ...prev, [m[1]]: msg.message }))
        break
      }
      case 'reconnect': {
        if (msg.symbol) {
          setSymbolErrors(prev => {
            const next = { ...prev }
            delete next[msg.symbol]
            return next
          })
          if (!hasHistoricalDataRef.current) setHistoryLoadKey(n => n + 1)
        }
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

  const handleIntervalSwitch = useCallback(async () => {
    if (!pendingInterval || isSwitching) return
    const iv  = pendingInterval
    const st  = statusRef.current
    const mp  = markPricesRef.current
    setPendingInterval(null)
    setIsSwitching(true)

    try {
      await botApi.stop()
      await botApi.start({
        capital:   st.capital,
        symbols:   st.symbols,
        intervals: [iv],
        strategy:  st.strategy,
        recover:   false,
      })
      setHasHistoricalData(false)
      hasHistoricalDataRef.current = false
      setSignal(null)
      setAllMessages([])
      setFills([])
      setPositions([])
      setFillCount(0)
      setSymbolErrors({})
      setHistoryLoadKey(0)
      const newItems: WatchItem[] = st.symbols.map(sym => ({
        key:      `${sym}|${iv}`,
        symbol:   sym,
        interval: iv,
        price:    mp[sym] ?? 0,
        change:   0,
      }))
      setWatchItems(newItems)
      setActiveKey(`${st.symbols[0]}|${iv}`)
    } catch {
      // Restart failed — bot state is unchanged
    } finally {
      setIsSwitching(false)
    }
  }, [pendingInterval, isSwitching])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-4 h-12 bg-surface border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className={cn('w-2 h-2 rounded-full', connected ? 'bg-green' : 'bg-amber animate-pulse')} />
          <Badge variant={status.running ? 'pass' : 'muted'}>{status.running ? 'Live' : 'Stopped'}</Badge>
        </div>

        {activeKey && (
          <span className="text-sm font-mono font-semibold text-text">
            {activeSymbol}<span className="text-muted mx-1">·</span>{activeInterval?.toUpperCase()}
          </span>
        )}
        {status.strategy && (
          <span className="text-xs text-muted font-mono">{status.strategy}</span>
        )}

        <div className="flex items-center gap-5 ml-auto">
          <Metric label="Capital"   value={`$${fmtPrice(status.capital ?? 0)}`} />
          <Metric label="Open PnL"  value={fmtSign(totalPnl)}
            className={positions.length > 0 ? pnlClass(totalPnl) : 'text-muted'} />
          <Metric label="Positions" value={String(positions.length)} />
          <Metric label="Fills"     value={String(fillCount)} />
        </div>

        <Button variant="danger" size="sm" onClick={() => setShowStop(true)}>Stop</Button>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Left: market watch */}
        <div className="w-[140px] shrink-0 overflow-hidden">
          <MarketWatch
            items={watchItems}
            activeKey={activeKey}
            onSelect={setActiveKey}
            symbolErrors={symbolErrors}
          />
        </div>

        {/* Center: chart */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0">
          {/* Chart header */}
          <div className="flex items-center gap-3 px-3 h-9 shrink-0 border-b border-border bg-surface">
            <span className="text-sm font-semibold font-mono text-text shrink-0">
              {activeSymbol || '—'}<span className="text-muted mx-1">·</span>{activeInterval?.toUpperCase() || '—'}
            </span>
            {activePrice > 0 ? (
              <>
                <span className="text-sm font-mono tabular-nums text-text shrink-0">{fmtPrice(activePrice)}</span>
                <span className={cn('text-xs font-mono tabular-nums shrink-0', changeColor)}>
                  {fmtChange(activeChange)}
                </span>
              </>
            ) : (
              <span className="text-xs text-muted2 shrink-0">—</span>
            )}

            <div className="flex items-center gap-px ml-2 shrink-0">
              {TIMEFRAMES.map(tf => (
                <button
                  key={tf}
                  disabled={isSwitching}
                  onClick={() => tf !== activeInterval && setPendingInterval(prev => prev === tf ? null : tf)}
                  className={cn(
                    'px-1.5 py-0.5 text-xs font-mono rounded transition-colors',
                    tf === activeInterval
                      ? 'text-accent font-bold'
                      : tf === pendingInterval
                        ? 'text-accent/60'
                        : 'text-muted hover:text-muted2 hover:bg-s2'
                  )}
                >
                  {tf}
                </button>
              ))}
            </div>

            {pendingInterval && (
              <div className="flex items-center gap-1.5 shrink-0 text-xs">
                <span className="text-muted">→ {pendingInterval}?</span>
                <button
                  onClick={handleIntervalSwitch}
                  disabled={isSwitching}
                  className="text-green font-semibold hover:opacity-70"
                >
                  Restart
                </button>
                <button onClick={() => setPendingInterval(null)} className="text-muted hover:text-text">✕</button>
              </div>
            )}

            {hasHistoricalData && !connected && (
              <div className="flex items-center gap-1.5 ml-auto shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
                <span className="text-xs text-muted font-mono">reconnecting</span>
              </div>
            )}
          </div>

          <div className="relative flex-1 min-h-0">
            <TradingChart ref={chartRef} className="absolute inset-0" />
            {!hasHistoricalData && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none z-10">
                {historyError ? (
                  <>
                    <span className="text-sm text-red mb-1">Failed to load history</span>
                    <span className="text-xs text-muted text-center px-6">{historyError}</span>
                  </>
                ) : (
                  <>
                    <span className="w-2 h-2 rounded-full bg-muted animate-pulse mb-3" />
                    <span className="text-sm text-muted">
                      {isLoadingHistory ? 'Loading historical data…' : 'Connecting to market data…'}
                    </span>
                    <span className="text-xs text-muted2 mt-1">
                      {activeSymbol || '…'} · {activeInterval?.toUpperCase() || '…'}
                    </span>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right: signal panel */}
        <div className="w-[160px] shrink-0 overflow-hidden">
          <SignalPanel
            strategy={status.strategy ?? ''}
            activeKey={activeKey}
            signal={signal}
            positions={positions}
            markPrices={markPrices}
          />
        </div>
      </div>

      {/* Bottom panel */}
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
      <span className="text-xs text-muted">{label}</span>
      <span className={cn('text-sm font-mono font-semibold tabular-nums', className ?? 'text-text')}>{value}</span>
    </div>
  )
}
