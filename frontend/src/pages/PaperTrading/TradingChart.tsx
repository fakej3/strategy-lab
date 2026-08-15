import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react'
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type CandlestickSeriesOptions,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { Candle, BotWsMessage, OpenPosition } from '../../types'

export interface ChartHandle {
  setData(candles: Candle[]): void
  updateCandle(c: Extract<BotWsMessage, { type: 'candle' }>): void
  addSignal(s: Extract<BotWsMessage, { type: 'signal' }>): void
  addFill(f: Extract<BotWsMessage, { type: 'fill' }>): void
  setPosition(p: OpenPosition | null): void
  fitContent(): void
}

interface Props {
  className?: string
}

export const TradingChart = forwardRef<ChartHandle, Props>(function TradingChart({ className }, ref) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef    = useRef<ISeriesApi<'Histogram'> | null>(null)
  const markersRef   = useRef<SeriesMarker<Time>[]>([])
  const entryLineRef = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#080c12' },
        textColor:  '#556e86',
        fontFamily: '"JetBrains Mono", "Fira Code", monospace',
        fontSize:   10,
      },
      grid: {
        vertLines: { color: '#111a24' },
        horzLines: { color: '#111a24' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#2a4060', labelBackgroundColor: '#0d1b2a' },
        horzLine: { color: '#2a4060', labelBackgroundColor: '#0d1b2a' },
      },
      rightPriceScale: { borderColor: '#1c2b3a' },
      timeScale: { borderColor: '#1c2b3a', timeVisible: true, secondsVisible: false },
    })
    chartRef.current = chart

    const candles = chart.addCandlestickSeries({
      upColor:        '#10b981',
      downColor:      '#f43f5e',
      borderUpColor:  '#10b981',
      borderDownColor:'#f43f5e',
      wickUpColor:    '#10b981',
      wickDownColor:  '#f43f5e',
    } as Partial<CandlestickSeriesOptions>)
    candleRef.current = candles

    const volume = chart.addHistogramSeries({
      priceScaleId: 'vol',
      color:        '#243447',
    })
    volumeRef.current = volume
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

    return () => {
      chart.remove()
      chartRef.current  = null
      candleRef.current = null
      volumeRef.current = null
    }
  }, [])

  useImperativeHandle(ref, () => ({
    setData(candles: Candle[]) {
      if (!candleRef.current || !volumeRef.current) return
      const sorted = [...candles].sort((a, b) => a.time - b.time)
      candleRef.current.setData(sorted.map(c => ({
        time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close,
      })))
      volumeRef.current.setData(sorted.map(c => ({
        time: c.time as Time, value: c.volume,
        color: c.close >= c.open ? '#10b98130' : '#f43f5e30',
      })))
      markersRef.current = []
    },

    updateCandle(c) {
      if (!candleRef.current || !volumeRef.current) return
      const t = c.time as Time
      candleRef.current.update({ time: t, open: c.open, high: c.high, low: c.low, close: c.close })
      volumeRef.current.update({ time: t, value: c.volume, color: c.close >= c.open ? '#10b98130' : '#f43f5e30' })
    },

    addSignal(s) {
      if (!candleRef.current) return
      const ts = Math.floor(Date.now() / 1000) as Time
      const isBuy = s.signal.toUpperCase().includes('BUY') || s.signal.toUpperCase().includes('LONG')
      markersRef.current = [...markersRef.current, {
        time: ts,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: isBuy ? '#10b981' : '#f43f5e',
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        text: s.signal.toUpperCase(),
        size: 1,
      }]
      candleRef.current.setMarkers(markersRef.current)
    },

    addFill(f) {
      if (!candleRef.current) return
      const ts = Math.floor(Date.now() / 1000) as Time
      const isBuy = f.side.toUpperCase() === 'BUY'
      markersRef.current = [...markersRef.current, {
        time: ts,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: isBuy ? '#10b981' : '#f43f5e',
        shape: 'circle',
        text: `${f.side} ${f.size}@${f.fill_price}`,
        size: 0.5,
      }]
      candleRef.current.setMarkers(markersRef.current)
    },

    setPosition(p) {
      if (!candleRef.current) return
      if (entryLineRef.current) {
        try { candleRef.current.removePriceLine(entryLineRef.current) } catch {}
        entryLineRef.current = null
      }
      if (p) {
        entryLineRef.current = candleRef.current.createPriceLine({
          price: p.entry_price,
          color: p.direction === 'long' ? '#10b981' : '#f43f5e',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `Entry ${p.direction.toUpperCase()} ${p.symbol}`,
        })
      }
    },

    fitContent() {
      chartRef.current?.timeScale().fitContent()
    },
  }))

  return <div ref={containerRef} className={className} />
})
