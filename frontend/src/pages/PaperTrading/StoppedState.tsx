import { useState, FormEvent } from 'react'
import { botApi } from '../../api/bot'
import { Button } from '../../components/ui/Button'
import type { AvailableStrategy } from '../../types'

interface Props {
  strategies: AvailableStrategy[]
  error?: string
  onStarted: () => void
}

export function StoppedState({ strategies, error, onStarted }: Props) {
  const [loading, setL] = useState(false)
  const [err, setErr]   = useState(error ?? '')

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setErr('')
    const fd = new FormData(e.currentTarget)
    const capital   = Number(fd.get('capital') ?? 200)
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
    <div className="flex flex-col h-full">
      {/* Stopped top bar */}
      <div className="flex items-center gap-2 px-5 py-3 bg-surface border-b border-border">
        <span className="w-2 h-2 rounded-full bg-muted" />
        <span className="text-[11px] font-semibold uppercase tracking-widest text-muted">Stopped</span>
        <div className="ml-auto text-[11px] text-muted">EdgeLab · Paper Trading</div>
      </div>

      {/* Config form */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-xl">
          <h1 className="text-[16px] font-bold text-text mb-1">Configure Paper Bot</h1>

          {err && (
            <div className="px-3 py-2.5 mb-4 bg-red/10 border border-red/30 rounded-md text-red text-[11px]">{err}</div>
          )}

          <div className="mb-4 px-3 py-2.5 bg-accent/8 border border-accent/20 rounded-md text-[11px] text-accent/80">
            <strong className="text-accent">Paper Trading Mode</strong> — No real funds are used. Capital is simulated USDT.
            Orders are tracked locally; no Binance API key required for market data.
          </div>

          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="bg-surface border border-border rounded-md p-4">
              <div className="grid grid-cols-3 gap-3 mb-3">
                <Field label="Capital (USDT)" name="capital" type="number" defaultValue="200" hint="Paper capital — no real funds" />
                <Field label="Symbol(s)" name="symbols" defaultValue="BTCUSDT" hint="Comma-separated" />
                <Field label="Interval(s)" name="intervals" defaultValue="1h" hint="e.g. 1m,5m,1h" />
              </div>
              <div className="flex items-end gap-4">
                <div className="flex flex-col gap-1 flex-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Strategy</label>
                  <select name="strategy"
                    className="bg-bg border border-border rounded px-2.5 py-1.5 text-[12px] text-text focus:outline-none focus:border-accent">
                    {strategies.map(s => (
                      <option key={s.name} value={s.name}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <label className="flex items-center gap-2 cursor-pointer pb-1.5">
                  <input type="checkbox" name="recover" defaultChecked className="accent-accent" />
                  <span className="text-[12px] text-text">Recover open orders on restart</span>
                </label>
              </div>
            </div>

            <Button type="submit" variant="primary" size="md" loading={loading} disabled={strategies.length === 0}>
              ▶ Start Bot
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, hint }: {
  label: string; name: string; type?: string; defaultValue?: string; hint?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</label>
      <input type={type} name={name} defaultValue={defaultValue}
        className="bg-bg border border-border rounded px-2.5 py-1.5 text-[12px] text-text focus:outline-none focus:border-accent" />
      {hint && <div className="text-[10px] text-muted2">{hint}</div>}
    </div>
  )
}
