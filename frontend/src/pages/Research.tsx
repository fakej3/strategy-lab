import { useEffect, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap, BarChart2, Microscope, ChevronDown, FlaskConical, Plus, X } from 'lucide-react'
import { botApi } from '../api/bot'
import { jobsApi } from '../api/jobs'
import { cn } from '../lib/cn'
import type { AvailableStrategy } from '../types'

type Preset = 'quick' | 'standard' | 'deep'

const INTERVALS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
const POPULAR_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']

interface AnalysisConfig {
  runWalkForward: boolean
  trainBars: number
  testBars: number
  runMonteCarlo: boolean
  nSimulations: number
  runRobustness: boolean
  neighborSteps: number
  workers: number
  fastMode: boolean
}

const PRESETS: Record<Preset, AnalysisConfig> = {
  quick:    { runWalkForward: false, trainBars: 1008, testBars: 336, runMonteCarlo: false, nSimulations: 200, runRobustness: false, neighborSteps: 1, workers: 4, fastMode: true },
  standard: { runWalkForward: true,  trainBars: 1008, testBars: 336, runMonteCarlo: true,  nSimulations: 500, runRobustness: false, neighborSteps: 1, workers: 4, fastMode: false },
  deep:     { runWalkForward: true,  trainBars: 1008, testBars: 336, runMonteCarlo: true,  nSimulations: 1000, runRobustness: true, neighborSteps: 2, workers: 8, fastMode: false },
}

const PRESET_INFO: Record<Preset, { label: string; icon: React.ElementType; sub: string; time: string }> = {
  quick:    { label: 'Quick',    icon: Zap,        sub: 'Fast pass, no deep analysis', time: '~1 min' },
  standard: { label: 'Standard', icon: BarChart2,  sub: 'Walk-forward + Monte Carlo',  time: '~5 min' },
  deep:     { label: 'Deep',     icon: Microscope, sub: 'All analyses, all workers',   time: '~15 min' },
}

export function Research() {
  const navigate = useNavigate()
  const today    = new Date().toISOString().slice(0, 10)

  const [strategies,    setStrategies]    = useState<AvailableStrategy[]>([])
  const [selected,      setSelected]      = useState<string[]>([])
  const [preset,        setPreset]        = useState<Preset>('standard')
  const [analysis,      setAnalysis]      = useState<AnalysisConfig>(PRESETS.standard)
  const [symbols,       setSymbols]       = useState<string[]>(['BTCUSDT'])
  const [symbolInput,   setSymbolInput]   = useState('')
  const [interval,      setInterval]      = useState('1h')
  const [startDate,     setStartDate]     = useState('2024-01-01')
  const [endDate,       setEndDate]       = useState(today)
  const [showAdvanced,  setShowAdvanced]  = useState(false)
  const [loading,       setLoading]       = useState(false)
  const [error,         setError]         = useState('')

  useEffect(() => {
    botApi.availableStrategies().then(s => {
      setStrategies(s)
      if (s.length) setSelected(s.map(x => x.name))
    })
  }, [])

  function applyPreset(p: Preset) {
    setPreset(p)
    setAnalysis(PRESETS[p])
  }

  function addSymbol(sym: string) {
    const s = sym.toUpperCase().trim()
    if (s && !symbols.includes(s)) setSymbols(prev => [...prev, s])
    setSymbolInput('')
  }

  function removeSymbol(sym: string) {
    if (symbols.length > 1) setSymbols(prev => prev.filter(s => s !== sym))
  }

  function toggleStrategy(name: string) {
    setSelected(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name])
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    const fd = new FormData(e.currentTarget)
    const body: Record<string, unknown> = {
      symbols:          symbols.join(','),
      intervals:        interval,
      start_date:       startDate,
      end_date:         endDate,
      starting_capital: Number(fd.get('starting_capital') ?? 100000),
      fee_rate:         Number(fd.get('fee_rate') ?? 0.001),
      slippage_pct:     Number(fd.get('slippage') ?? 0.0005),
      stop_loss_pct:    fd.get('stop_loss') ? Number(fd.get('stop_loss')) : undefined,
      take_profit_pct:  fd.get('take_profit') ? Number(fd.get('take_profit')) : undefined,
      min_trades:       Number(fd.get('min_trades') ?? 10),
      max_drawdown_threshold: Number(fd.get('max_dd') ?? 0.35),
      strategies:       selected,
      run_walk_forward: analysis.runWalkForward,
      wf_train_bars:    analysis.trainBars,
      wf_test_bars:     analysis.testBars,
      run_monte_carlo:  analysis.runMonteCarlo,
      mc_simulations:   analysis.nSimulations,
      run_robustness:   analysis.runRobustness,
      robustness_steps: analysis.neighborSteps,
      n_workers:        analysis.workers,
      fast_mode:        analysis.fastMode,
      verbose:          false,
    }
    setLoading(true)
    try {
      const { job_id } = await jobsApi.submit(body)
      navigate(`/jobs/${job_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const canRun = selected.length > 0 && symbols.length > 0

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <div>
          <span className="page-title">Research</span>
          <span className="text-muted2 mx-2">·</span>
          <span className="text-xs text-muted">Find strategies worth trading</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <form onSubmit={submit}>
          <div className="max-w-3xl mx-auto px-6 py-8 flex flex-col gap-7">

            {error && (
              <div className="px-4 py-3 bg-red/8 border border-red/20 rounded-xl text-red text-sm">{error}</div>
            )}

            {/* STEP 1: Market */}
            <section>
              <StepHeader n={1} label="Market" sub="What to test" />
              <div className="mt-4 flex flex-col gap-5">

                {/* Symbol chips */}
                <div>
                  <label className="field-label block mb-2">Symbols</label>
                  <div className="flex flex-wrap gap-2 mb-2">
                    {symbols.map(s => (
                      <span key={s} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-accent/10 border border-accent/20 text-accent text-xs font-mono font-semibold rounded-lg">
                        {s}
                        {symbols.length > 1 && (
                          <button type="button" onClick={() => removeSymbol(s)} className="opacity-60 hover:opacity-100">
                            <X size={10} />
                          </button>
                        )}
                      </span>
                    ))}
                    {/* Quick add */}
                    {POPULAR_SYMBOLS.filter(s => !symbols.includes(s)).slice(0, 3).map(s => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => addSymbol(s)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 bg-s2 border border-border text-muted text-xs font-mono rounded-lg hover:border-border2 hover:text-text transition-colors"
                      >
                        <Plus size={9} />
                        {s}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={symbolInput}
                      onChange={e => setSymbolInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addSymbol(symbolInput) } }}
                      placeholder="e.g. ADAUSDT"
                      className="field-input max-w-[200px] text-xs font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => addSymbol(symbolInput)}
                      disabled={!symbolInput.trim()}
                      className="px-3 py-2 bg-s3 border border-border text-muted text-xs rounded-lg hover:text-text hover:border-border2 transition-colors disabled:opacity-40"
                    >
                      Add
                    </button>
                  </div>
                </div>

                {/* Interval pills */}
                <div>
                  <label className="field-label block mb-2">Timeframe</label>
                  <div className="flex flex-wrap gap-2">
                    {INTERVALS.map(iv => (
                      <button
                        key={iv}
                        type="button"
                        onClick={() => setInterval(iv)}
                        className={cn(
                          'px-3 py-1.5 text-xs font-mono font-medium rounded-lg border transition-all',
                          interval === iv
                            ? 'bg-accent/15 border-accent/40 text-accent'
                            : 'bg-s2 border-border text-muted hover:border-border2 hover:text-text',
                        )}
                      >
                        {iv}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Date range */}
                <div className="grid grid-cols-2 gap-4 max-w-sm">
                  <div>
                    <label className="field-label block mb-1.5">From</label>
                    <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="field-input text-xs" />
                  </div>
                  <div>
                    <label className="field-label block mb-1.5">To</label>
                    <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="field-input text-xs" />
                  </div>
                </div>
              </div>
            </section>

            {/* STEP 2: Depth */}
            <section>
              <StepHeader n={2} label="Analysis Depth" sub="How thorough" />
              <div className="grid grid-cols-3 gap-3 mt-4">
                {(Object.entries(PRESET_INFO) as [Preset, typeof PRESET_INFO[Preset]][]).map(([key, info]) => {
                  const Icon = info.icon
                  const active = preset === key
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => applyPreset(key)}
                      className={cn(
                        'flex flex-col items-start gap-2 px-4 py-4 rounded-xl border text-left transition-all',
                        active
                          ? 'border-accent/40 bg-accent/8 shadow-sm shadow-accent/5'
                          : 'border-border bg-surface hover:border-border2',
                      )}
                    >
                      <div className="flex items-center justify-between w-full">
                        <Icon size={16} className={active ? 'text-accent' : 'text-muted'} />
                        <span className={cn('text-[10px] font-mono', active ? 'text-accent/70' : 'text-muted2')}>{info.time}</span>
                      </div>
                      <div className={cn('text-sm font-semibold', active ? 'text-accent' : 'text-text')}>{info.label}</div>
                      <div className="text-xs text-muted leading-snug">{info.sub}</div>
                    </button>
                  )
                })}
              </div>
            </section>

            {/* STEP 3: Strategies */}
            <section>
              <div className="flex items-center justify-between mb-4">
                <StepHeader n={3} label="Strategies" sub="What to test" />
                {strategies.length > 1 && (
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setSelected(strategies.map(s => s.name))}
                      className="text-xs text-muted hover:text-accent transition-colors">All</button>
                    <span className="text-muted2">·</span>
                    <button type="button" onClick={() => setSelected([])}
                      className="text-xs text-muted hover:text-red transition-colors">None</button>
                  </div>
                )}
              </div>
              {strategies.length === 0 ? (
                <div className="flex items-center gap-2 py-4 text-muted text-sm">
                  <span className="w-3 h-3 border border-muted/30 border-t-muted rounded-full animate-spin" />
                  Loading strategies…
                </div>
              ) : (
                <div className="grid gap-2">
                  {strategies.map(s => {
                    const paramCount = Object.keys(s.param_space ?? {}).length
                    const totalCombos = Object.values(s.param_space ?? {}).reduce((acc, vals) => acc * (vals as unknown[]).length, 1)
                    const isSelected = selected.includes(s.name)
                    return (
                      <label
                        key={s.name}
                        className={cn(
                          'flex items-center gap-3 px-4 py-3.5 rounded-xl border cursor-pointer transition-all',
                          isSelected
                            ? 'border-accent/30 bg-accent/5'
                            : 'border-border bg-surface hover:border-border2',
                        )}
                      >
                        <div className={cn(
                          'w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors',
                          isSelected ? 'bg-accent border-accent' : 'border-border2 bg-s2',
                        )}>
                          {isSelected && (
                            <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                              <path d="M1 3L3 5L7 1" stroke="#090C12" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          )}
                        </div>
                        <input type="checkbox" checked={isSelected} onChange={() => toggleStrategy(s.name)} className="sr-only" />
                        <div className="flex-1 min-w-0">
                          <span className={cn('text-sm font-semibold', isSelected ? 'text-text' : 'text-muted')}>{s.name}</span>
                          <span className="text-xs text-muted2 ml-2">{paramCount} param{paramCount !== 1 ? 's' : ''}</span>
                        </div>
                        <span className="text-xs font-mono text-muted2 shrink-0">{totalCombos} configs</span>
                      </label>
                    )
                  })}
                </div>
              )}
            </section>

            {/* Advanced toggle */}
            <section>
              <button
                type="button"
                onClick={() => setShowAdvanced(v => !v)}
                className="flex items-center gap-2 text-xs text-muted hover:text-text transition-colors group"
              >
                <ChevronDown size={14} className={cn('transition-transform', showAdvanced ? 'rotate-180' : '')} />
                <span>Advanced settings</span>
                {!showAdvanced && (
                  <span className="text-muted2">— fees, portfolio, walk-forward params</span>
                )}
              </button>

              {showAdvanced && (
                <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 p-5 bg-surface border border-border rounded-xl">
                  <AdvField label="Capital (USD)" name="starting_capital" type="number" defaultValue="100000" />
                  <AdvField label="Fee Rate" name="fee_rate" type="number" step="0.0001" defaultValue="0.001" hint="0.001 = 0.1%" />
                  <AdvField label="Slippage" name="slippage" type="number" step="0.0001" defaultValue="0.0005" />
                  <AdvField label="Min Trades" name="min_trades" type="number" defaultValue="10" />
                  <AdvField label="Max Drawdown" name="max_dd" type="number" step="0.01" defaultValue="0.35" hint="e.g. 0.35 = 35%" />
                  <AdvField label="Stop Loss" name="stop_loss" type="number" step="0.01" hint="e.g. 0.05 = 5%" />
                  {analysis.runWalkForward && (
                    <>
                      <AdvField label="WF Train Bars" name="wf_train_bars" type="number" defaultValue={String(analysis.trainBars)} />
                      <AdvField label="WF Test Bars" name="wf_test_bars" type="number" defaultValue={String(analysis.testBars)} />
                    </>
                  )}
                  {analysis.runMonteCarlo && (
                    <AdvField label="MC Simulations" name="mc_simulations" type="number" defaultValue={String(analysis.nSimulations)} />
                  )}
                  <AdvField label="Workers" name="n_workers" type="number" defaultValue={String(analysis.workers)} />
                </div>
              )}
            </section>

            {/* Run CTA */}
            <div className="sticky bottom-0 pb-6">
              <button
                type="submit"
                disabled={loading || !canRun}
                className="w-full flex items-center justify-center gap-3 px-6 py-4 bg-accent text-bg text-base font-bold rounded-2xl hover:bg-accent-dim active:scale-[0.99] transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-accent/10"
              >
                {loading ? (
                  <>
                    <span className="w-5 h-5 border-2 border-bg/30 border-t-bg rounded-full animate-spin" />
                    Launching…
                  </>
                ) : (
                  <>
                    <FlaskConical size={18} />
                    Run Research
                    {selected.length > 0 && symbols.length > 0 && (
                      <span className="opacity-70 font-normal text-sm">
                        · {selected.length} {selected.length === 1 ? 'strategy' : 'strategies'} · {symbols.join(', ')} · {interval}
                      </span>
                    )}
                  </>
                )}
              </button>
              {!canRun && !loading && (
                <p className="text-center text-xs text-muted mt-2">Select at least one strategy to run</p>
              )}
            </div>

          </div>
        </form>
      </div>
    </div>
  )
}

function StepHeader({ n, label, sub }: { n: number; label: string; sub: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-6 h-6 rounded-full bg-accent/15 border border-accent/30 text-accent text-xs font-bold flex items-center justify-center shrink-0">{n}</span>
      <div>
        <span className="text-sm font-semibold text-text">{label}</span>
        <span className="text-muted2 text-xs ml-2">{sub}</span>
      </div>
    </div>
  )
}

function AdvField({ label, name, type = 'text', defaultValue, hint, step }: {
  label: string; name: string; type?: string; defaultValue?: string; hint?: string; step?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="field-label">{label}{hint && <span className="text-muted2 ml-1">({hint})</span>}</label>
      <input type={type} name={name} defaultValue={defaultValue} step={step} className="field-input text-xs" />
    </div>
  )
}
