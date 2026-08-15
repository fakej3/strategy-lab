import { useEffect, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { botApi } from '../api/bot'
import { jobsApi } from '../api/jobs'
import { Button } from '../components/ui/Button'
import type { AvailableStrategy } from '../types'

export function Research() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<AvailableStrategy[]>([])
  const [selected, setSelected]     = useState<string[]>([])
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')

  const today = new Date().toISOString().slice(0, 10)

  useEffect(() => {
    botApi.availableStrategies().then(s => {
      setStrategies(s)
      if (s.length) setSelected([s[0].name])
    })
  }, [])

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    const fd = new FormData(e.currentTarget)
    const raw: Record<string, unknown> = {}

    fd.forEach((v, k) => {
      if (raw[k] !== undefined) {
        raw[k] = Array.isArray(raw[k]) ? [...raw[k] as unknown[], v] : [raw[k], v]
      } else {
        raw[k] = v
      }
    })

    ;(['run_walk_forward', 'run_monte_carlo', 'run_robustness', 'fast_mode', 'verbose'] as const).forEach(cb => {
      raw[cb] = fd.has(cb)
    })

    raw.strategies = selected

    setLoading(true)
    try {
      const { job_id } = await jobsApi.submit(raw)
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
    <div className="p-6 max-w-3xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">New Research Run</h1>
      <p className="text-[12px] text-muted mb-5">Configure and launch the research pipeline</p>

      {error && (
        <div className="px-3 py-2.5 mb-4 bg-red/10 border border-red/30 rounded-md text-red text-[11px]">{error}</div>
      )}

      <form onSubmit={submit} className="flex flex-col gap-5">
        {/* Market Data */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Market Data</div>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <Field label="Symbols" name="symbols" defaultValue="BTCUSDT" hint="Comma-separated Binance symbols" />
            <Field label="Intervals" name="intervals" defaultValue="1h" hint="Comma-separated timeframes" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Start Date" name="start_date" type="date" defaultValue="2024-01-01" />
            <Field label="End Date"   name="end_date"   type="date" defaultValue={today} />
          </div>
        </section>

        {/* Portfolio */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Portfolio Settings</div>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <Field label="Starting Capital ($)" name="starting_capital" type="number" defaultValue="100000" />
            <Field label="Fee Rate" name="fee_rate" type="number" step="0.0001" defaultValue="0.001" hint="0.001 = 0.1%" />
            <Field label="Slippage" name="slippage" type="number" step="0.0001" defaultValue="0.0005" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Stop Loss (optional)" name="stop_loss" type="number" step="0.01" hint="e.g. 0.05 for 5%" />
            <Field label="Take Profit (optional)" name="take_profit" type="number" step="0.01" hint="e.g. 0.15 for 15%" />
          </div>
        </section>

        {/* Gate */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Quality Gate Thresholds</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Minimum Trades" name="min_trades" type="number" defaultValue="10" />
            <Field label="Max Drawdown Threshold" name="max_drawdown_threshold" type="number" step="0.01" defaultValue="0.35" hint="Reject if max DD exceeds this" />
          </div>
        </section>

        {/* Strategy Selection */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Strategy Selection</div>
          <div className="flex flex-col gap-2">
            {strategies.map(s => (
              <label key={s.name} className="flex items-center gap-2 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={selected.includes(s.name)}
                  onChange={() => toggleStrategy(s.name)}
                  className="w-3.5 h-3.5 accent-accent"
                />
                <span className="text-[12px] text-text group-hover:text-accent transition-colors">{s.name}</span>
                <span className="text-[10px] text-muted">— {Object.keys(s.param_space ?? {}).length} param(s)</span>
              </label>
            ))}
          </div>
        </section>

        {/* Walk-Forward */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Walk-Forward Analysis</div>
          <CheckField name="run_walk_forward" label="Enable Walk-Forward Analysis" />
          <div className="grid grid-cols-2 gap-3 mt-3">
            <Field label="Training Bars" name="train_bars" type="number" defaultValue="1008" hint="~6 weeks of 1h bars" />
            <Field label="Test Bars"     name="test_bars"  type="number" defaultValue="336"  hint="~2 weeks of 1h bars" />
          </div>
        </section>

        {/* Monte Carlo */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Monte Carlo Simulation</div>
          <CheckField name="run_monte_carlo" label="Enable Monte Carlo" />
          <div className="mt-3">
            <Field label="Simulations" name="n_simulations" type="number" defaultValue="500" />
          </div>
        </section>

        {/* Robustness */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Parameter Robustness</div>
          <CheckField name="run_robustness" label="Enable Robustness Analysis (neighbor parameter testing)" />
          <div className="mt-3">
            <Field label="Neighbor Steps" name="neighbor_steps" type="number" defaultValue="1" hint="±steps in each parameter dimension" />
          </div>
        </section>

        {/* Execution */}
        <section className="bg-surface border border-border rounded-md p-4">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Execution</div>
          <div className="mb-3">
            <Field label="Workers" name="workers" type="number" defaultValue="4" hint="Parallel backtest processes" />
          </div>
          <div className="flex gap-4">
            <CheckField name="fast_mode" label="Fast Mode (skip WF + MC)" />
            <CheckField name="verbose"   label="Verbose Logging" />
          </div>
        </section>

        <div className="flex gap-3">
          <Button type="submit" variant="primary" size="md" loading={loading} disabled={selected.length === 0}>
            Launch Research Run
          </Button>
          <Button type="button" variant="secondary" size="md" onClick={() => history.back()}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, hint, step }: {
  label: string; name: string; type?: string; defaultValue?: string; hint?: string; step?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</label>
      <input
        type={type}
        name={name}
        defaultValue={defaultValue}
        step={step}
        className="bg-bg border border-border rounded px-2.5 py-1.5 text-[12px] text-text placeholder:text-muted2 focus:outline-none focus:border-accent"
      />
      {hint && <div className="text-[10px] text-muted2">{hint}</div>}
    </div>
  )
}

function CheckField({ name, label }: { name: string; label: string }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" name={name} className="w-3.5 h-3.5 accent-accent" />
      <span className="text-[12px] text-text">{label}</span>
    </label>
  )
}
