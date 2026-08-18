import { useEffect, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { FlaskConical, Zap, BarChart2, Microscope } from 'lucide-react'
import { botApi } from '../api/bot'
import { jobsApi } from '../api/jobs'
import { cn } from '../lib/cn'
import type { AvailableStrategy } from '../types'

type Preset = 'quick' | 'standard' | 'deep'

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
  quick: {
    runWalkForward: false, trainBars: 1008, testBars: 336,
    runMonteCarlo:  false, nSimulations: 200,
    runRobustness:  false, neighborSteps: 1,
    workers: 4, fastMode: true,
  },
  standard: {
    runWalkForward: true,  trainBars: 1008, testBars: 336,
    runMonteCarlo:  true,  nSimulations: 500,
    runRobustness:  false, neighborSteps: 1,
    workers: 4, fastMode: false,
  },
  deep: {
    runWalkForward: true,  trainBars: 1008, testBars: 336,
    runMonteCarlo:  true,  nSimulations: 1000,
    runRobustness:  true,  neighborSteps: 2,
    workers: 8, fastMode: false,
  },
}

const PRESET_META: Record<Preset, { label: string; icon: React.ElementType; sub: string }> = {
  quick:    { label: 'Quick',    icon: Zap,        sub: 'Fast pass, no deep analysis' },
  standard: { label: 'Standard', icon: BarChart2,  sub: 'Walk-forward + Monte Carlo' },
  deep:     { label: 'Deep',     icon: Microscope, sub: 'All analyses, more workers' },
}

export function Research() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<AvailableStrategy[]>([])
  const [selected,   setSelected]   = useState<string[]>([])
  const [preset,     setPreset]      = useState<Preset>('standard')
  const [analysis,   setAnalysis]    = useState<AnalysisConfig>(PRESETS.standard)
  const [loading,    setLoading]     = useState(false)
  const [error,      setError]       = useState('')
  const today = new Date().toISOString().slice(0, 10)

  useEffect(() => {
    botApi.availableStrategies().then(s => {
      setStrategies(s)
      if (s.length) setSelected([s[0].name])
    })
  }, [])

  function applyPreset(p: Preset) {
    setPreset(p)
    setAnalysis(PRESETS[p])
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    const fd = new FormData(e.currentTarget)
    const body: Record<string, unknown> = {
      symbols:          String(fd.get('symbols') ?? 'BTCUSDT'),
      intervals:        String(fd.get('intervals') ?? '1h'),
      start_date:       fd.get('start_date'),
      end_date:         fd.get('end_date'),
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

  function toggleStrategy(name: string) {
    setSelected(prev =>
      prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Research Run</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {error && (
          <div className="mx-6 mt-4 px-4 py-3 bg-red/8 border border-red/20 rounded-lg text-red text-sm">{error}</div>
        )}

        <form onSubmit={submit}>
          <div className="p-6">
            {/* Preset selector */}
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-3">
                <label className="section-label">Analysis Depth</label>
              </div>
              <div className="grid grid-cols-3 gap-3">
                {(Object.entries(PRESET_META) as [Preset, typeof PRESET_META[Preset]][]).map(([key, meta]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => applyPreset(key)}
                    className={cn(
                      'flex items-start gap-3 px-4 py-3 rounded-lg border text-left transition-colors',
                      preset === key
                        ? 'border-accent bg-accent-bg text-accent'
                        : 'border-border bg-surface hover:border-border2 text-muted hover:text-text',
                    )}
                  >
                    <meta.icon size={16} className="mt-0.5 shrink-0" />
                    <div>
                      <div className={cn('text-sm font-semibold', preset === key ? 'text-accent' : 'text-text')}>
                        {meta.label}
                      </div>
                      <div className="text-xs mt-0.5">{meta.sub}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-[1fr_280px] gap-6">
              {/* Left: config panels */}
              <div className="flex flex-col gap-5">
                {/* Market Data */}
                <ConfigSection title="Market Data">
                  <div className="grid grid-cols-2 gap-4">
                    <Field label="Symbols" name="symbols" defaultValue="BTCUSDT" hint="Comma-separated" />
                    <Field label="Intervals" name="intervals" defaultValue="1h" hint="e.g. 1m, 1h, 4h" />
                    <Field label="Start Date" name="start_date" type="date" defaultValue="2024-01-01" />
                    <Field label="End Date"   name="end_date"   type="date" defaultValue={today} />
                  </div>
                </ConfigSection>

                {/* Portfolio */}
                <ConfigSection title="Portfolio">
                  <div className="grid grid-cols-3 gap-4">
                    <Field label="Capital (USD)" name="starting_capital" type="number" defaultValue="100000" />
                    <Field label="Fee Rate"       name="fee_rate"        type="number" step="0.0001" defaultValue="0.001" hint="0.001 = 0.1%" />
                    <Field label="Slippage"       name="slippage"        type="number" step="0.0001" defaultValue="0.0005" />
                    <Field label="Stop Loss"      name="stop_loss"       type="number" step="0.01"   hint="e.g. 0.05 = 5%" />
                    <Field label="Take Profit"    name="take_profit"     type="number" step="0.01"   hint="e.g. 0.15 = 15%" />
                    <Field label="Min Trades"     name="min_trades"      type="number" defaultValue="10" />
                  </div>
                </ConfigSection>

                {/* Quality Gate */}
                <ConfigSection title="Quality Gate">
                  <div className="grid grid-cols-2 gap-4">
                    <Field label="Max Drawdown" name="max_dd" type="number" step="0.01" defaultValue="0.35" hint="Reject if DD exceeds this (e.g. 0.35 = 35%)" />
                  </div>
                </ConfigSection>

                {/* Analysis (controlled by preset) */}
                <ConfigSection title="Analysis">
                  <div className="grid grid-cols-2 gap-5">
                    {/* Walk-Forward */}
                    <div className="flex flex-col gap-3">
                      <label className="flex items-center gap-2.5 cursor-pointer">
                        <ToggleCheck
                          checked={analysis.runWalkForward}
                          onChange={v => setAnalysis(a => ({ ...a, runWalkForward: v }))}
                        />
                        <span className="text-sm text-text font-medium">Walk-Forward</span>
                      </label>
                      {analysis.runWalkForward && (
                        <div className="grid grid-cols-2 gap-3 pl-6">
                          <NumField label="Train bars" value={analysis.trainBars}
                            onChange={v => setAnalysis(a => ({ ...a, trainBars: v }))} />
                          <NumField label="Test bars" value={analysis.testBars}
                            onChange={v => setAnalysis(a => ({ ...a, testBars: v }))} />
                        </div>
                      )}
                    </div>

                    {/* Monte Carlo */}
                    <div className="flex flex-col gap-3">
                      <label className="flex items-center gap-2.5 cursor-pointer">
                        <ToggleCheck
                          checked={analysis.runMonteCarlo}
                          onChange={v => setAnalysis(a => ({ ...a, runMonteCarlo: v }))}
                        />
                        <span className="text-sm text-text font-medium">Monte Carlo</span>
                      </label>
                      {analysis.runMonteCarlo && (
                        <div className="pl-6">
                          <NumField label="Simulations" value={analysis.nSimulations}
                            onChange={v => setAnalysis(a => ({ ...a, nSimulations: v }))} />
                        </div>
                      )}
                    </div>

                    {/* Robustness */}
                    <div className="flex flex-col gap-3">
                      <label className="flex items-center gap-2.5 cursor-pointer">
                        <ToggleCheck
                          checked={analysis.runRobustness}
                          onChange={v => setAnalysis(a => ({ ...a, runRobustness: v }))}
                        />
                        <span className="text-sm text-text font-medium">Robustness Testing</span>
                      </label>
                      {analysis.runRobustness && (
                        <div className="pl-6">
                          <NumField label="Neighbor steps" value={analysis.neighborSteps}
                            onChange={v => setAnalysis(a => ({ ...a, neighborSteps: v }))} />
                        </div>
                      )}
                    </div>

                    {/* Workers + Fast Mode */}
                    <div className="flex flex-col gap-3">
                      <NumField label="Workers" value={analysis.workers}
                        onChange={v => setAnalysis(a => ({ ...a, workers: v }))} />
                      <label className="flex items-center gap-2.5 cursor-pointer">
                        <ToggleCheck
                          checked={analysis.fastMode}
                          onChange={v => setAnalysis(a => ({ ...a, fastMode: v }))}
                        />
                        <span className="text-sm text-text">Fast Mode</span>
                      </label>
                    </div>
                  </div>
                </ConfigSection>
              </div>

              {/* Right: strategy selection + launch */}
              <div className="flex flex-col gap-4">
                <ConfigSection title="Strategies">
                  <div className="flex flex-col gap-2">
                    {strategies.length === 0 && (
                      <p className="text-sm text-muted">Loading strategies…</p>
                    )}
                    {strategies.map(s => (
                      <label key={s.name} className="flex items-start gap-3 cursor-pointer group rounded-md px-3 py-2 hover:bg-s3 transition-colors">
                        <input
                          type="checkbox"
                          checked={selected.includes(s.name)}
                          onChange={() => toggleStrategy(s.name)}
                          className="mt-0.5 w-3.5 h-3.5 accent-amber shrink-0"
                        />
                        <div>
                          <div className="text-sm text-text group-hover:text-accent transition-colors font-medium">{s.name}</div>
                          <div className="text-xs text-muted mt-0.5">
                            {Object.keys(s.param_space ?? {}).length} param{Object.keys(s.param_space ?? {}).length !== 1 ? 's' : ''}
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                </ConfigSection>

                <button
                  type="submit"
                  disabled={loading || selected.length === 0}
                  className="flex items-center justify-center gap-2 px-4 py-3 bg-accent text-bg text-sm font-bold rounded-lg hover:bg-accent-dim transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? (
                    <span className="w-4 h-4 border-2 border-bg border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <FlaskConical size={15} />
                  )}
                  {loading ? 'Launching…' : `Launch Run · ${selected.length} strateg${selected.length !== 1 ? 'ies' : 'y'}`}
                </button>

                {selected.length === 0 && (
                  <p className="text-xs text-muted text-center">Select at least one strategy</p>
                )}
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

function ConfigSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border">
        <span className="text-xs font-semibold text-muted">{title}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, hint, step }: {
  label: string; name: string; type?: string; defaultValue?: string; hint?: string; step?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="field-label">{label}</label>
      <input type={type} name={name} defaultValue={defaultValue} step={step} className="field-input" />
      {hint && <div className="text-xs text-muted2">{hint}</div>}
    </div>
  )
}

function NumField({ label, value, onChange }: {
  label: string; value: number; onChange: (v: number) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="field-label">{label}</label>
      <input
        type="number"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="field-input"
      />
    </div>
  )
}

function ToggleCheck({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <input
      type="checkbox"
      checked={checked}
      onChange={e => onChange(e.target.checked)}
      className="w-3.5 h-3.5 accent-amber shrink-0"
    />
  )
}
