import { useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CandlestickChart, Zap, Plus, X } from 'lucide-react'
import { botApi } from '../../api/bot'
import type { AvailableStrategy } from '../../types'
import { cn } from '../../lib/cn'

interface Props {
  strategies: AvailableStrategy[]
  error?: string
  onStarted: () => void
}

const QUICK_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'ADAUSDT']
const INTERVALS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
const CAPITAL_PRESETS = [
  { label: '$1K',  value: 1000 },
  { label: '$5K',  value: 5000 },
  { label: '$10K', value: 10000 },
  { label: '$50K', value: 50000 },
]

export function StoppedState({ strategies, error, onStarted }: Props) {
  const [searchParams] = useSearchParams()

  const prefillSymbol   = searchParams.get('symbol')   ?? 'BTCUSDT'
  const prefillInterval = searchParams.get('interval') ?? '1h'
  const prefillStrategy = searchParams.get('strategy') ?? (strategies[0]?.name ?? '')
  const hasPrefill      = searchParams.has('symbol') || searchParams.has('strategy')

  const [symbols,       setSymbols]       = useState<string[]>([prefillSymbol].filter(Boolean))
  const [interval,      setInterval]      = useState(prefillInterval)
  const [strategy,      setStrategy]      = useState(prefillStrategy)
  const [capital,       setCapital]       = useState(10000)
  const [customCapital, setCustomCapital] = useState('')
  const [useCustomCap,  setUseCustomCap]  = useState(false)
  const [recover,       setRecover]       = useState(true)
  const [customSym,     setCustomSym]     = useState('')
  const [loading,       setLoading]       = useState(false)
  const [err,           setErr]           = useState(error ?? '')

  const addSymbol = useCallback((sym: string) => {
    const s = sym.trim().toUpperCase()
    if (!s) return
    setSymbols(prev => prev.includes(s) ? prev : [...prev, s])
    setCustomSym('')
  }, [])

  const removeSymbol = useCallback((sym: string) => {
    setSymbols(prev => prev.filter(s => s !== sym))
  }, [])

  const toggleSymbol = useCallback((sym: string) => {
    setSymbols(prev => prev.includes(sym) ? prev.filter(s => s !== sym) : [...prev, sym])
  }, [])

  async function launch() {
    setErr('')
    if (symbols.length === 0) { setErr('Select at least one symbol.'); return }
    const cap = useCustomCap ? Number(customCapital) : capital
    if (!cap || cap < 1) { setErr('Capital must be at least $1.'); return }

    setLoading(true)
    try {
      await botApi.start({
        capital: cap,
        symbols,
        intervals: [interval],
        strategy,
        recover,
      })
      onStarted()
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : String(ex))
    } finally {
      setLoading(false)
    }
  }

  const finalCapital = useCustomCap ? Number(customCapital) || 0 : capital

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Status bar */}
      <div className="flex items-center gap-3 px-5 h-11 bg-surface border-b border-border shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-muted2 shrink-0" />
        <span className="text-sm font-semibold text-text">Paper Trading</span>
        <span className="text-muted2">·</span>
        <span className="text-sm text-muted2">Stopped</span>
        <span className="ml-auto text-xs text-muted2 font-mono">Simulation only · No real funds</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <div className="max-w-2xl mx-auto px-6 py-8">

          {/* Prefill notice */}
          {hasPrefill && (
            <div className="flex items-center gap-2.5 px-4 py-3 mb-6 border border-accent/20 bg-accent-bg rounded-xl">
              <Zap size={14} className="text-accent shrink-0" />
              <span className="text-sm text-accent font-medium">Strategy loaded from research</span>
              <span className="text-sm text-muted">— confirm and launch</span>
            </div>
          )}

          {/* Error */}
          {err && (
            <div className="px-4 py-3 mb-5 border border-red/20 bg-red/8 rounded-xl text-red text-sm">{err}</div>
          )}

          {/* Strategy */}
          <ConfigSection label="Strategy" icon="⚡">
            <div className="flex flex-col gap-2">
              {strategies.length === 0 ? (
                <div className="text-sm text-muted px-4 py-3 bg-s2 rounded-lg">No strategies available</div>
              ) : strategies.map(s => (
                <button
                  key={s.name}
                  onClick={() => setStrategy(s.name)}
                  className={cn(
                    'flex items-center gap-3 w-full text-left px-4 py-3 rounded-xl border transition-all',
                    strategy === s.name
                      ? 'border-accent/40 bg-accent/8 ring-1 ring-accent/20'
                      : 'border-border bg-surface hover:border-border2 hover:bg-s2',
                  )}
                >
                  <div className={cn(
                    'w-2 h-2 rounded-full shrink-0 mt-0.5 transition-colors',
                    strategy === s.name ? 'bg-accent' : 'bg-muted2',
                  )} />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-text">{s.name}</div>
                    <div className="text-xs text-muted mt-0.5 font-mono">
                      {s.params?.length ?? (s.param_space ? Object.keys(s.param_space).length : 2)} params
                      {s.param_space && ` · ${Object.values(s.param_space).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1)} configs`}
                    </div>
                  </div>
                  {strategy === s.name && (
                    <span className="text-[11px] font-bold text-accent px-2 py-0.5 bg-accent/10 rounded-full">Selected</span>
                  )}
                </button>
              ))}
            </div>
          </ConfigSection>

          {/* Market */}
          <ConfigSection label="Market" icon="📈">
            <div className="flex flex-wrap gap-2 mb-3">
              {QUICK_SYMBOLS.map(sym => {
                const active = symbols.includes(sym)
                return (
                  <button
                    key={sym}
                    onClick={() => toggleSymbol(sym)}
                    className={cn(
                      'px-3 py-1.5 rounded-lg text-xs font-semibold font-mono border transition-all',
                      active
                        ? 'bg-accent text-bg border-accent'
                        : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                    )}
                  >
                    {sym.replace('USDT', '')}
                    {active && ' ✓'}
                  </button>
                )
              })}
            </div>
            {/* Custom symbol */}
            <div className="flex gap-2">
              <input
                type="text"
                value={customSym}
                onChange={e => setCustomSym(e.target.value.toUpperCase())}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addSymbol(customSym))}
                placeholder="e.g. XRPUSDT"
                className="field-input flex-1 text-xs font-mono"
              />
              <button
                type="button"
                onClick={() => addSymbol(customSym)}
                className="px-3 py-2 bg-s3 border border-border rounded-lg text-xs text-muted hover:text-text hover:border-border2 transition-colors"
              >
                <Plus size={12} />
              </button>
            </div>
            {/* Selected symbols */}
            {symbols.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {symbols.map(sym => (
                  <span
                    key={sym}
                    className="flex items-center gap-1 px-2.5 py-1 bg-accent/10 border border-accent/20 rounded-full text-xs font-mono text-accent"
                  >
                    {sym}
                    <button onClick={() => removeSymbol(sym)} className="hover:opacity-70 transition-opacity">
                      <X size={10} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </ConfigSection>

          {/* Interval */}
          <ConfigSection label="Timeframe" icon="⏱">
            <div className="flex gap-1.5 flex-wrap">
              {INTERVALS.map(iv => (
                <button
                  key={iv}
                  onClick={() => setInterval(iv)}
                  className={cn(
                    'px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border transition-all',
                    interval === iv
                      ? 'bg-accent text-bg border-accent'
                      : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                  )}
                >
                  {iv}
                </button>
              ))}
            </div>
          </ConfigSection>

          {/* Capital */}
          <ConfigSection label="Starting Capital" icon="💰">
            <div className="flex gap-1.5 flex-wrap mb-3">
              {CAPITAL_PRESETS.map(p => (
                <button
                  key={p.value}
                  onClick={() => { setCapital(p.value); setUseCustomCap(false) }}
                  className={cn(
                    'px-4 py-1.5 rounded-lg text-xs font-mono font-semibold border transition-all',
                    !useCustomCap && capital === p.value
                      ? 'bg-accent text-bg border-accent'
                      : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                  )}
                >
                  {p.label}
                </button>
              ))}
              <button
                onClick={() => setUseCustomCap(true)}
                className={cn(
                  'px-4 py-1.5 rounded-lg text-xs font-semibold border transition-all',
                  useCustomCap
                    ? 'bg-accent text-bg border-accent'
                    : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                )}
              >
                Custom
              </button>
            </div>
            {useCustomCap && (
              <input
                type="number"
                value={customCapital}
                onChange={e => setCustomCapital(e.target.value)}
                placeholder="Enter amount"
                min="1"
                className="field-input max-w-[200px] text-sm font-mono"
                autoFocus
              />
            )}
          </ConfigSection>

          {/* Recover toggle */}
          <div className="mb-6">
            <label className="flex items-center gap-3 cursor-pointer select-none group">
              <div
                onClick={() => setRecover(r => !r)}
                className={cn(
                  'w-9 h-5 rounded-full border transition-all flex items-center px-0.5',
                  recover ? 'bg-accent border-accent' : 'bg-s3 border-border',
                )}
              >
                <div className={cn(
                  'w-4 h-4 rounded-full bg-white shadow transition-all',
                  recover ? 'translate-x-4' : 'translate-x-0',
                )} />
              </div>
              <div>
                <div className="text-sm font-medium text-text">Recover open positions on start</div>
                <div className="text-xs text-muted">Restore existing positions from the exchange</div>
              </div>
            </label>
          </div>

          {/* Summary + Launch */}
          <div className="bg-surface border border-border rounded-xl p-4 mb-4">
            <div className="flex items-center gap-4 flex-wrap text-xs text-muted mb-4">
              <span className="font-semibold text-text">{strategy || '—'}</span>
              <span>·</span>
              <span className="font-mono">{symbols.join(', ') || 'no symbol'}</span>
              <span>·</span>
              <span className="font-mono">{interval}</span>
              <span>·</span>
              <span className="font-mono">${finalCapital.toLocaleString()}</span>
            </div>
            <button
              onClick={launch}
              disabled={loading || strategies.length === 0 || symbols.length === 0}
              className="w-full flex items-center justify-center gap-2.5 py-3.5 bg-green/10 border border-green/20 text-green text-sm font-bold rounded-lg hover:bg-green/15 hover:border-green/35 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="w-4 h-4 border-2 border-green/40 border-t-green rounded-full animate-spin" />
              ) : (
                <CandlestickChart size={16} />
              )}
              {loading ? 'Launching…' : 'Launch Paper Trading'}
            </button>
          </div>

          <p className="text-xs text-center text-muted2">
            Simulates real orders against live Binance market data · No API keys required
          </p>
        </div>
      </div>
    </div>
  )
}

function ConfigSection({
  label, icon, children,
}: {
  label: string
  icon: string
  children: React.ReactNode
}) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-base leading-none">{icon}</span>
        <span className="text-sm font-semibold text-text">{label}</span>
      </div>
      {children}
    </div>
  )
}
