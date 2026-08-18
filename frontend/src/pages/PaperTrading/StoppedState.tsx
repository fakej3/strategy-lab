import { useState, FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CandlestickChart, Zap, ShieldCheck } from 'lucide-react'
import { botApi } from '../../api/bot'
import type { AvailableStrategy } from '../../types'

interface Props {
  strategies: AvailableStrategy[]
  error?: string
  onStarted: () => void
}

export function StoppedState({ strategies, error, onStarted }: Props) {
  const [searchParams] = useSearchParams()
  const [loading, setL] = useState(false)
  const [err, setErr]   = useState(error ?? '')

  const prefillSymbol   = searchParams.get('symbol')   ?? 'BTCUSDT'
  const prefillInterval = searchParams.get('interval') ?? '1h'
  const prefillStrategy = searchParams.get('strategy') ?? ''
  const hasPrefill      = searchParams.has('symbol') || searchParams.has('strategy')

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setErr('')
    const fd = new FormData(e.currentTarget)
    const capital   = Number(fd.get('capital') ?? 10000)
    const rawSyms   = String(fd.get('symbols') ?? 'BTCUSDT')
    const rawIvs    = String(fd.get('intervals') ?? '1h')
    const strategy  = String(fd.get('strategy') ?? 'EMACrossover')
    const recover   = fd.has('recover')
    const symbols   = rawSyms.split(',').map(s => s.trim()).filter(Boolean)
    const intervals = rawIvs.split(',').map(s => s.trim()).filter(Boolean)

    setL(true)
    try {
      await botApi.start({ capital, symbols, intervals, strategy, recover })
      onStarted()
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex))
    } finally {
      setL(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Status bar */}
      <div className="flex items-center gap-3 px-6 h-12 bg-surface border-b border-border shrink-0">
        <span className="w-2 h-2 rounded-full bg-muted2 shrink-0" />
        <span className="text-sm font-semibold text-muted">Paper Trading</span>
        <span className="text-muted2 mx-1">·</span>
        <span className="text-sm text-muted2">Stopped</span>
        <span className="ml-auto text-xs text-muted2 font-mono">No real funds · Simulation only</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <div className="max-w-2xl mx-auto px-6 py-12">

          {/* Hero */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-green/10 border border-green/20 mb-5">
              <CandlestickChart size={26} className="text-green" />
            </div>
            <h1 className="text-2xl font-bold text-text tracking-tight mb-2">Launch Paper Trading</h1>
            <p className="text-sm text-muted max-w-sm mx-auto">
              Simulate live trading with real market data. No real funds required.
            </p>
          </div>

          {/* Prefill notice */}
          {hasPrefill && (
            <div className="flex items-start gap-3 px-4 py-3.5 mb-6 border border-accent/20 bg-accent-bg rounded-xl">
              <Zap size={15} className="text-accent shrink-0 mt-0.5" />
              <div className="text-sm">
                <span className="text-accent font-semibold">Strategy pre-loaded from research — </span>
                <span className="text-muted">review settings below and click Start.</span>
              </div>
            </div>
          )}

          {/* Error */}
          {err && (
            <div className="px-4 py-3 mb-6 border border-red/20 bg-red/8 rounded-xl text-red text-sm">{err}</div>
          )}

          {/* Config form */}
          <form id="botcfg" onSubmit={submit}>
            <div className="bg-surface border border-border rounded-xl overflow-hidden mb-4">
              <div className="px-5 py-3 border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase tracking-wider">Configuration</span>
              </div>
              <div className="p-5 flex flex-col gap-5">

                {/* Capital */}
                <div>
                  <label className="field-label block mb-1.5">Starting Capital (USDT)</label>
                  <input
                    type="number"
                    name="capital"
                    defaultValue="10000"
                    min="1"
                    className="field-input max-w-[200px]"
                  />
                  <p className="text-xs text-muted2 mt-1">Simulated USDT — not real money</p>
                </div>

                {/* Symbols + Intervals */}
                <div className="grid grid-cols-2 gap-5">
                  <div>
                    <label className="field-label block mb-1.5">Symbol(s)</label>
                    <input
                      type="text"
                      name="symbols"
                      defaultValue={prefillSymbol}
                      placeholder="BTCUSDT, ETHUSDT"
                      className="field-input"
                    />
                    <p className="text-xs text-muted2 mt-1">Comma-separated for multi-symbol</p>
                  </div>
                  <div>
                    <label className="field-label block mb-1.5">Interval(s)</label>
                    <input
                      type="text"
                      name="intervals"
                      defaultValue={prefillInterval}
                      placeholder="1h"
                      className="field-input"
                    />
                    <p className="text-xs text-muted2 mt-1">e.g. 1m, 5m, 1h, 4h, 1d</p>
                  </div>
                </div>

                {/* Strategy */}
                <div>
                  <label className="field-label block mb-1.5">Strategy</label>
                  <select
                    name="strategy"
                    defaultValue={prefillStrategy || undefined}
                    className="field-select w-full"
                  >
                    {strategies.map(s => (
                      <option key={s.name} value={s.name}>{s.name}</option>
                    ))}
                  </select>
                </div>

                {/* Recover toggle */}
                <label className="flex items-center gap-3 cursor-pointer select-none">
                  <input type="checkbox" name="recover" defaultChecked className="w-3.5 h-3.5 accent-amber shrink-0" />
                  <div>
                    <span className="text-sm text-text font-medium">Recover open orders on start</span>
                    <p className="text-xs text-muted mt-0.5">Attempt to restore existing positions from the exchange</p>
                  </div>
                </label>
              </div>
            </div>

            {/* Info strip */}
            <div className="flex items-start gap-3 px-4 py-3.5 mb-5 bg-s2 border border-border rounded-xl">
              <ShieldCheck size={15} className="text-muted shrink-0 mt-0.5" />
              <p className="text-xs text-muted leading-relaxed">
                Paper trading simulates real orders against live Binance market data. No API keys required.
                All trades, positions and P&amp;L are tracked locally. You can stop and restart at any time.
              </p>
            </div>

            {/* Submit */}
            <button
              type="submit"
              form="botcfg"
              disabled={loading || strategies.length === 0}
              className="w-full flex items-center justify-center gap-2.5 px-6 py-3.5 bg-green/10 border border-green/20 text-green text-sm font-bold rounded-xl hover:bg-green/15 hover:border-green/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="w-4 h-4 border-2 border-green/40 border-t-green rounded-full animate-spin" />
              ) : (
                <CandlestickChart size={16} />
              )}
              {loading ? 'Starting…' : 'Start Paper Trading'}
            </button>
          </form>

        </div>
      </div>
    </div>
  )
}
