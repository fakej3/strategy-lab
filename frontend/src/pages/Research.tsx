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
    <div className="flex flex-col h-full">
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">New Research Run</span>
          <span className="ml-3 text-[10px] text-muted">Configure and launch the research pipeline</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {error && (
          <div className="mx-5 mt-4 px-3 py-2 bg-red/8 border border-red/25 text-red text-[10px]">{error}</div>
        )}

        <form onSubmit={submit} className="p-5">
          <div className="grid grid-cols-[1fr_260px] gap-5 max-w-5xl">
            {/* Left column: config */}
            <div className="flex flex-col gap-4">

              {/* Market Data */}
              <Panel title="Market Data">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Symbols" name="symbols" defaultValue="BTCUSDT" hint="Comma-separated" />
                  <Field label="Intervals" name="intervals" defaultValue="1h" hint="Comma-separated" />
                  <Field label="Start Date" name="start_date" type="date" defaultValue="2024-01-01" />
                  <Field label="End Date"   name="end_date"   type="date" defaultValue={today} />
                </div>
              </Panel>

              {/* Portfolio */}
              <Panel title="Portfolio">
                <div className="grid grid-cols-3 gap-3">
                  <Field label="Capital ($)" name="starting_capital" type="number" defaultValue="100000" />
                  <Field label="Fee Rate"    name="fee_rate"         type="number" step="0.0001" defaultValue="0.001" hint="0.001 = 0.1%" />
                  <Field label="Slippage"    name="slippage"         type="number" step="0.0001" defaultValue="0.0005" />
                  <Field label="Stop Loss"   name="stop_loss"        type="number" step="0.01"   hint="e.g. 0.05 = 5%" />
                  <Field label="Take Profit" name="take_profit"      type="number" step="0.01"   hint="e.g. 0.15 = 15%" />
                </div>
              </Panel>

              {/* Quality Gate */}
              <Panel title="Quality Gate">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Min Trades"     name="min_trades"              type="number" defaultValue="10" />
                  <Field label="Max Drawdown %" name="max_drawdown_threshold"  type="number" step="0.01" defaultValue="0.35" hint="Reject if DD exceeds this" />
                </div>
              </Panel>

              {/* Analysis */}
              <Panel title="Analysis">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <CheckField name="run_walk_forward" label="Walk-Forward" />
                    <div className="grid grid-cols-2 gap-2 mt-2 pl-4">
                      <Field label="Train Bars" name="train_bars" type="number" defaultValue="1008" />
                      <Field label="Test Bars"  name="test_bars"  type="number" defaultValue="336" />
                    </div>
                  </div>
                  <div>
                    <CheckField name="run_monte_carlo" label="Monte Carlo" />
                    <div className="mt-2 pl-4">
                      <Field label="Simulations" name="n_simulations" type="number" defaultValue="500" />
                    </div>
                  </div>
                  <div>
                    <CheckField name="run_robustness" label="Robustness Testing" />
                    <div className="mt-2 pl-4">
                      <Field label="Neighbor Steps" name="neighbor_steps" type="number" defaultValue="1" />
                    </div>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Field label="Workers" name="workers" type="number" defaultValue="4" hint="Parallel processes" />
                    <div className="flex gap-3">
                      <CheckField name="fast_mode" label="Fast Mode" />
                      <CheckField name="verbose"   label="Verbose" />
                    </div>
                  </div>
                </div>
              </Panel>

            </div>

            {/* Right column: strategy selection + submit */}
            <div className="flex flex-col gap-4">
              <Panel title="Strategies">
                <div className="flex flex-col gap-1.5">
                  {strategies.length === 0 && (
                    <p className="text-[10px] text-muted">Loading strategies…</p>
                  )}
                  {strategies.map(s => (
                    <label key={s.name} className="flex items-start gap-2 cursor-pointer group">
                      <input
                        type="checkbox"
                        checked={selected.includes(s.name)}
                        onChange={() => toggleStrategy(s.name)}
                        className="mt-0.5 w-3 h-3 accent-accent shrink-0"
                      />
                      <div>
                        <div className="text-[11px] text-text group-hover:text-accent transition-colors leading-tight">{s.name}</div>
                        <div className="text-[9px] text-muted">{Object.keys(s.param_space ?? {}).length} param(s)</div>
                      </div>
                    </label>
                  ))}
                </div>
              </Panel>

              <div className="flex gap-2">
                <Button type="submit" variant="primary" size="sm" loading={loading} disabled={selected.length === 0}>
                  Launch Run
                </Button>
                <Button type="button" variant="secondary" size="sm" onClick={() => history.back()}>
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border">
      <div className="px-3 py-1.5 border-b border-border bg-surface">
        <span className="section-label">{title}</span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, hint, step }: {
  label: string; name: string; type?: string; defaultValue?: string; hint?: string; step?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="field-label">{label}</label>
      <input
        type={type}
        name={name}
        defaultValue={defaultValue}
        step={step}
        className="field-input"
      />
      {hint && <div className="text-[9px] text-muted2">{hint}</div>}
    </div>
  )
}

function CheckField({ name, label }: { name: string; label: string }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" name={name} className="w-3 h-3 accent-accent" />
      <span className="text-[11px] text-text">{label}</span>
    </label>
  )
}
