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

  const prefillSymbol   = searchParams.get('symbol')    ?? 'BTCUSDT'
  const prefillInterval = searchParams.get('interval')  ?? '1h'
  const prefillStrategy = searchParams.get('strategy')  ?? (strategies[0]?.name ?? '')
  const prefillResultId = searchParams.get('result_id') ? Number(searchParams.get('result_id')) : undefined
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
        ...(prefillResultId != null ? { result_id: prefillResultId } : {}),
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
      <div className="flex items-center gap-3 px-5 h-10 bg-surface border-b border-border shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-muted2 shrink-0" />
        <span className="text-sm font-semibold text-text">Paper Trading</span>
        <span className="text-muted2 text-xs">·</span>
        <span className="text-xs text-muted2">Stopped</span>
        {hasPrefill && (
          <>
            <span className="text-muted2 text-xs">·</span>
            <span className="flex items-center gap-1.5 text-xs text-accent">
              <Zap size={11} />
              Loaded from research
            </span>
          </>
        )}
        <span className="ml-auto text-xs text-muted2 font-mono">Simulation only · No real funds</span>
      </div>

      {/* Split layout */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left: config */}
        <div className="flex-1 overflow-y-auto scrollbar-thin border-r border-border">
          <div className="p-6 max-w-2xl flex flex-col gap-6">

            {err && (
              <div className="px-4 py-3 border border-red/20 bg-red/8 rounded-xl text-red text-sm">{err}</div>
            )}

            {/* Strategy */}
            <Section label="01 STRATEGY">
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
                      'w-2 h-2 rounded-full shrink-0 transition-colors',
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
            </Section>

            {/* Market */}
            <Section label="02 MARKET">
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
            </Section>

            {/* Timeframe */}
            <Section label="03 TIMEFRAME">
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
            </Section>

            {/* Capital */}
            <Section label="04 CAPITAL">
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
            </Section>

            {/* Recover toggle */}
            <label className="flex items-center gap-3 cursor-pointer select-none">
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
        </div>

        {/* Right: summary + launch */}
        <div className="w-[260px] shrink-0 flex flex-col bg-surface">
          <div className="p-5 flex flex-col gap-4 flex-1">
            <div className="text-[10px] font-semibold tracking-widest text-muted2">DEPLOY SUMMARY</div>

            <table className="w-full text-xs">
              <tbody>
                {[
                  { l: 'Strategy',   v: strategy || '—' },
                  { l: 'Symbols',    v: symbols.length ? symbols.map(s => s.replace('USDT','')).join(', ') : '—' },
                  { l: 'Timeframe',  v: interval },
                  { l: 'Capital',    v: finalCapital > 0 ? `$${finalCapital.toLocaleString()}` : '—' },
                  { l: 'Mode',       v: 'Paper (Simulation)' },
                  { l: 'Recover',    v: recover ? 'Yes' : 'No' },
                ].map(({ l, v }) => (
                  <tr key={l} className="border-b border-border/50">
                    <td className="py-2 text-muted2 pr-3 w-[80px]">{l}</td>
                    <td className="py-2 text-text font-mono text-[11px] break-all">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="mt-auto pt-4">
              <button
                onClick={launch}
                disabled={loading || strategies.length === 0 || symbols.length === 0}
                className="w-full flex items-center justify-center gap-2.5 py-3 bg-green/10 border border-green/20 text-green text-sm font-bold rounded-lg hover:bg-green/15 hover:border-green/35 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <span className="w-4 h-4 border-2 border-green/40 border-t-green rounded-full animate-spin" />
                ) : (
                  <CandlestickChart size={15} />
                )}
                {loading ? 'Launching…' : 'Launch Paper Trading →'}
              </button>
              <p className="text-[10px] text-center text-muted2 mt-3 leading-relaxed">
                Simulates real orders against live Binance data. No API keys required.
              </p>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-3">{label}</div>
      {children}
    </div>
  )
}
