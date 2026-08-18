import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap, BarChart2, Microscope, Plus, X, FlaskConical, ChevronRight } from 'lucide-react'
import { botApi } from '../api/bot'
import { jobsApi } from '../api/jobs'
import { cn } from '../lib/cn'
import type { AvailableStrategy } from '../types'

type Preset = 'quick' | 'standard' | 'deep'

const INTERVALS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
const POPULAR_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'ADAUSDT', 'DOGEUSDT']

interface AnalysisConfig {
  runWalkForward: boolean; trainBars: number; testBars: number
  runMonteCarlo: boolean; nSimulations: number
  runRobustness: boolean; neighborSteps: number
  workers: number; fastMode: boolean
}

const PRESETS: Record<Preset, AnalysisConfig> = {
  quick:    { runWalkForward: false, trainBars: 1008, testBars: 336, runMonteCarlo: false, nSimulations: 200, runRobustness: false, neighborSteps: 1, workers: 4, fastMode: true },
  standard: { runWalkForward: true,  trainBars: 1008, testBars: 336, runMonteCarlo: true,  nSimulations: 500, runRobustness: false, neighborSteps: 1, workers: 4, fastMode: false },
  deep:     { runWalkForward: true,  trainBars: 1008, testBars: 336, runMonteCarlo: true,  nSimulations: 1000, runRobustness: true, neighborSteps: 2, workers: 8, fastMode: false },
}

const PRESET_INFO: Record<Preset, { icon: React.ElementType; time: string; tags: string[] }> = {
  quick:    { icon: Zap,        time: '~1 min',  tags: ['No walk-forward', 'No MC', 'Fast'] },
  standard: { icon: BarChart2,  time: '~5 min',  tags: ['Walk-forward', 'Monte Carlo'] },
  deep:     { icon: Microscope, time: '~15 min', tags: ['Walk-forward', 'Monte Carlo', 'Robustness'] },
}

const today = new Date().toISOString().slice(0, 10)

export function Research() {
  const navigate    = useNavigate()
  const [strategies, setStrategies] = useState<AvailableStrategy[]>([])
  const [selected,   setSelected]   = useState<string[]>([])
  const [preset,     setPreset]     = useState<Preset>('standard')
  const [analysis,   setAnalysis]   = useState<AnalysisConfig>(PRESETS.standard)
  const [symbols,    setSymbols]    = useState<string[]>(['BTCUSDT'])
  const [symbolInput, setSymbolInput] = useState('')
  const [interval,   setInterval]   = useState('1h')
  const [startDate,  setStartDate]  = useState('2024-01-01')
  const [endDate,    setEndDate]    = useState(today)
  const [capital,    setCapital]    = useState(100000)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')

  useEffect(() => {
    botApi.availableStrategies().then(s => {
      setStrategies(s)
      if (s.length) setSelected(s.map(x => x.name))
    })
  }, [])

  function applyPreset(p: Preset) { setPreset(p); setAnalysis(PRESETS[p]) }

  function addSymbol(sym: string) {
    const s = sym.toUpperCase().trim()
    if (s && !symbols.includes(s)) setSymbols(prev => [...prev, s])
    setSymbolInput('')
  }

  function removeSymbol(sym: string) {
    if (symbols.length > 1) setSymbols(prev => prev.filter(s => s !== sym))
  }

  async function launch() {
    setError('')
    if (selected.length === 0) { setError('Select at least one strategy'); return }
    if (symbols.length === 0)  { setError('Select at least one symbol');   return }
    setLoading(true)
    try {
      const body: Record<string, unknown> = {
        symbols: symbols.join(','), intervals: interval,
        start_date: startDate, end_date: endDate,
        starting_capital: capital,
        fee_rate: 0.001, slippage_pct: 0.0005,
        min_trades: 10, max_drawdown_threshold: 0.35,
        strategies: selected,
        run_walk_forward: analysis.runWalkForward,
        wf_train_bars: analysis.trainBars, wf_test_bars: analysis.testBars,
        run_monte_carlo: analysis.runMonteCarlo, mc_simulations: analysis.nSimulations,
        run_robustness: analysis.runRobustness, robustness_steps: analysis.neighborSteps,
        n_workers: analysis.workers, fast_mode: analysis.fastMode, verbose: false,
      }
      const { job_id } = await jobsApi.submit(body)
      navigate(`/jobs/${job_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setLoading(false)
    }
  }

  const configCount = strategies.reduce((acc, s) => {
    if (!selected.includes(s.name)) return acc
    const n = s.param_space ? Object.values(s.param_space).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1) : 1
    return acc + (n as number)
  }, 0)

  const totalRuns = configCount * symbols.length

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Header */}
      <div className="shrink-0 flex items-center justify-between px-5 h-10 border-b border-border bg-surface">
        <div className="flex items-center gap-2 text-xs text-muted2">
          <span className="text-text font-semibold">Research</span>
          <ChevronRight size={12} />
          <span>New Run</span>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono text-muted2">
          {totalRuns > 0 && <span className="text-accent">{totalRuns} configs to test</span>}
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex">
        {/* Config panel */}
        <div className="flex-1 overflow-y-auto scrollbar-thin border-r border-border">
          <div className="p-5 max-w-2xl flex flex-col gap-6">

            {error && (
              <div className="px-3 py-2.5 bg-red/8 border border-red/20 rounded-lg text-red text-xs">{error}</div>
            )}

            {/* MARKET */}
            <Block step="01" label="MARKET" sub="Which assets to test">
              {/* Symbol chips */}
              <div className="flex flex-wrap gap-1.5 mb-3">
                {POPULAR_SYMBOLS.map(sym => {
                  const active = symbols.includes(sym)
                  return (
                    <button
                      key={sym}
                      type="button"
                      onClick={() => active ? removeSymbol(sym) : addSymbol(sym)}
                      className={cn(
                        'px-2.5 py-1 rounded text-[11px] font-mono font-semibold border transition-all',
                        active
                          ? 'bg-accent text-bg border-accent'
                          : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                      )}
                    >
                      {sym.replace('USDT', '')}
                    </button>
                  )
                })}
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={symbolInput}
                    onChange={e => setSymbolInput(e.target.value.toUpperCase())}
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addSymbol(symbolInput))}
                    placeholder="XRPUSDT"
                    className="w-24 px-2 py-1 bg-s2 border border-border rounded text-[11px] font-mono text-text placeholder:text-muted2 outline-none focus:border-accent/50"
                  />
                  <button
                    type="button"
                    onClick={() => addSymbol(symbolInput)}
                    className="px-2 py-1 bg-s2 border border-border rounded text-muted hover:text-text hover:border-border2 transition-colors"
                  >
                    <Plus size={10} />
                  </button>
                </div>
              </div>
              {/* Selected */}
              {symbols.some(s => !POPULAR_SYMBOLS.includes(s)) && (
                <div className="flex flex-wrap gap-1">
                  {symbols.filter(s => !POPULAR_SYMBOLS.includes(s)).map(s => (
                    <span key={s} className="flex items-center gap-1 px-2 py-0.5 bg-accent/10 border border-accent/20 rounded text-[11px] font-mono text-accent">
                      {s}
                      <button type="button" onClick={() => removeSymbol(s)}><X size={9} /></button>
                    </span>
                  ))}
                </div>
              )}

              {/* Timeframe */}
              <div className="mt-3">
                <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-2">TIMEFRAME</div>
                <div className="flex gap-1.5 flex-wrap">
                  {INTERVALS.map(iv => (
                    <button
                      key={iv}
                      type="button"
                      onClick={() => setInterval(iv)}
                      className={cn(
                        'px-2.5 py-1 rounded text-[11px] font-mono font-semibold border transition-all',
                        interval === iv
                          ? 'bg-accent text-bg border-accent'
                          : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                      )}
                    >
                      {iv}
                    </button>
                  ))}
                </div>
              </div>

              {/* Date range */}
              <div className="mt-3 flex gap-3">
                <div>
                  <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-1">FROM</div>
                  <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                    className="px-2 py-1.5 bg-s2 border border-border rounded text-xs font-mono text-text outline-none focus:border-accent/50" />
                </div>
                <div>
                  <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-1">TO</div>
                  <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                    className="px-2 py-1.5 bg-s2 border border-border rounded text-xs font-mono text-text outline-none focus:border-accent/50" />
                </div>
              </div>
            </Block>

            {/* STRATEGY */}
            <Block step="02" label="STRATEGY" sub="What to test">
              {strategies.length === 0 ? (
                <div className="text-xs text-muted">Loading strategies…</div>
              ) : strategies.map(s => {
                const configs = s.param_space
                  ? Object.values(s.param_space).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1)
                  : 1
                const params = s.params?.length ?? (s.param_space ? Object.keys(s.param_space).length : 0)
                const isSelected = selected.includes(s.name)
                return (
                  <button
                    key={s.name}
                    type="button"
                    onClick={() => setSelected(prev => isSelected ? prev.filter(n => n !== s.name) : [...prev, s.name])}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left transition-all',
                      isSelected
                        ? 'border-accent/40 bg-accent/8'
                        : 'border-border bg-s2 hover:border-border2',
                    )}
                  >
                    <div className={cn('w-2 h-2 rounded-full shrink-0', isSelected ? 'bg-accent' : 'bg-muted2')} />
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-text">{s.name}</div>
                      <div className="text-[11px] text-muted font-mono mt-0.5">{params} params · {configs as number} configs</div>
                    </div>
                    {isSelected && <span className="text-[10px] font-bold text-accent px-1.5 py-0.5 bg-accent/10 rounded">SELECTED</span>}
                  </button>
                )
              })}
            </Block>

            {/* DEPTH */}
            <Block step="03" label="DEPTH" sub="How thorough">
              <div className="grid grid-cols-3 gap-2">
                {(['quick', 'standard', 'deep'] as Preset[]).map(p => {
                  const info = PRESET_INFO[p]
                  const Icon = info.icon
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => applyPreset(p)}
                      className={cn(
                        'flex flex-col gap-2 px-3 py-3 rounded-lg border text-left transition-all',
                        preset === p
                          ? 'border-accent/50 bg-accent/8 ring-1 ring-accent/20'
                          : 'border-border bg-s2 hover:border-border2',
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <Icon size={13} className={preset === p ? 'text-accent' : 'text-muted2'} />
                        <span className={cn('text-[10px] font-mono font-semibold',
                          p === 'quick' ? 'text-green' : p === 'standard' ? 'text-accent' : 'text-amber'
                        )}>{info.time}</span>
                      </div>
                      <div className="text-xs font-semibold text-text capitalize">{p}</div>
                      <div className="flex flex-col gap-0.5">
                        {info.tags.map(t => (
                          <div key={t} className="text-[10px] text-muted">{t}</div>
                        ))}
                      </div>
                    </button>
                  )
                })}
              </div>
            </Block>

            {/* Capital */}
            <Block step="04" label="CAPITAL" sub="Starting simulation budget">
              <div className="flex gap-2 flex-wrap">
                {[10000, 50000, 100000, 250000].map(v => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setCapital(v)}
                    className={cn(
                      'px-3 py-1.5 rounded text-xs font-mono font-semibold border transition-all',
                      capital === v
                        ? 'bg-accent text-bg border-accent'
                        : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                    )}
                  >
                    ${v.toLocaleString()}
                  </button>
                ))}
              </div>
            </Block>
          </div>
        </div>

        {/* Right: launch panel */}
        <div className="w-[260px] shrink-0 flex flex-col bg-surface overflow-y-auto">
          <div className="p-4 flex flex-col gap-4 flex-1">

            {/* Config summary */}
            <div>
              <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-3">RUN SUMMARY</div>
              <div className="flex flex-col gap-2">
                {[
                  { l: 'Symbols',    v: symbols.join(', ') || '—' },
                  { l: 'Timeframe',  v: interval },
                  { l: 'Period',     v: `${startDate.slice(0,7)} – ${endDate.slice(0,7)}` },
                  { l: 'Strategy',   v: selected.join(', ') || '—' },
                  { l: 'Depth',      v: preset.charAt(0).toUpperCase() + preset.slice(1) },
                  { l: 'Capital',    v: `$${capital.toLocaleString()}` },
                ].map(({ l, v }) => (
                  <div key={l} className="flex items-start justify-between gap-2">
                    <span className="text-[10px] text-muted2 shrink-0">{l}</span>
                    <span className="text-[11px] font-mono text-text text-right">{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-border pt-3">
              <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-2">SCOPE</div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-3xl font-bold font-mono text-text tabular-nums">{totalRuns}</span>
                <span className="text-xs text-muted">configs</span>
              </div>
              <div className="text-[10px] text-muted mt-0.5">{configCount} params × {symbols.length} symbol{symbols.length !== 1 ? 's' : ''}</div>
            </div>

            <div className="border-t border-border pt-3">
              <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-2">ANALYSES</div>
              {[
                { l: 'Walk-forward',  v: analysis.runWalkForward },
                { l: 'Monte Carlo',   v: analysis.runMonteCarlo },
                { l: 'Robustness',    v: analysis.runRobustness },
                { l: 'Fast mode',     v: analysis.fastMode },
              ].map(({ l, v }) => (
                <div key={l} className="flex items-center justify-between py-0.5">
                  <span className="text-[10px] text-muted">{l}</span>
                  <span className={cn('text-[10px] font-semibold', v ? 'text-green' : 'text-muted2')}>{v ? 'ON' : 'OFF'}</span>
                </div>
              ))}
            </div>

            <div className="mt-auto pt-4">
              <button
                type="button"
                disabled={loading || selected.length === 0 || symbols.length === 0}
                onClick={launch}
                className="w-full flex items-center justify-center gap-2 py-3 bg-accent text-bg text-sm font-bold rounded-lg hover:bg-amber-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <>
                    <span className="w-4 h-4 border-2 border-bg/40 border-t-bg rounded-full animate-spin" />
                    Launching…
                  </>
                ) : (
                  <>
                    <FlaskConical size={14} />
                    RUN RESEARCH →
                  </>
                )}
              </button>
              <p className="text-[10px] text-center text-muted2 mt-2">Results appear in Jobs when complete</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Block({ step, label, sub, children }: {
  step: string; label: string; sub: string; children: React.ReactNode
}) {
  return (
    <div>
      <div className="flex items-center gap-3 mb-3">
        <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-s3 text-[10px] font-bold font-mono text-muted2 shrink-0">{step}</div>
        <div>
          <div className="text-xs font-bold tracking-widest text-text">{label}</div>
          <div className="text-[10px] text-muted">{sub}</div>
        </div>
      </div>
      <div className="ml-10">{children}</div>
    </div>
  )
}
