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
      <div className="flex items-center gap-2 px-4 h-10 bg-surface border-b border-border shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-muted2" />
        <span className="text-[9px] font-semibold uppercase tracking-widest text-muted">Stopped</span>
        <span className="ml-auto text-[9px] text-muted2 font-mono">EdgeLab · Paper Trading</span>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {err && (
          <div className="px-3 py-2 mb-4 border border-red/25 bg-red/8 text-red text-[10px]">{err}</div>
        )}

        <form id="botcfg" onSubmit={submit}>
          <div className="grid grid-cols-[1fr_260px] gap-5">
            {/* Left: config panel */}
            <div className="border border-border">
              <div className="px-3 py-1.5 border-b border-border bg-surface">
                <span className="section-label">Configuration</span>
              </div>
              <div className="p-3 grid grid-cols-3 gap-3">
                <Field label="Capital (USDT)" name="capital"   type="number" defaultValue="200" />
                <Field label="Symbol(s)"      name="symbols"   defaultValue="BTCUSDT" hint="Comma-separated" />
                <Field label="Interval(s)"    name="intervals" defaultValue="1h" hint="e.g. 1m, 1h, 4h" />
              </div>
              <div className="px-3 pb-3 flex items-end gap-4">
                <div className="flex flex-col gap-1 flex-1">
                  <label className="field-label">Strategy</label>
                  <select name="strategy" className="field-select w-full">
                    {strategies.map(s => (
                      <option key={s.name} value={s.name}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <label className="flex items-center gap-2 cursor-pointer pb-0.5">
                  <input type="checkbox" name="recover" defaultChecked className="accent-accent w-3 h-3" />
                  <span className="text-[10px] text-muted">Recover open orders</span>
                </label>
              </div>
            </div>

            {/* Right: info + launch */}
            <div className="flex flex-col gap-3">
              <div className="border border-accent/20 bg-accent-bg px-3 py-3 text-[10px] text-muted leading-relaxed">
                <div className="text-accent font-semibold text-[11px] mb-1">Paper Trading</div>
                No real funds used. Capital is simulated USDT. No Binance API key required.
              </div>
              <Button
                form="botcfg"
                type="submit"
                variant="primary"
                size="sm"
                loading={loading}
                disabled={strategies.length === 0}
              >
                Start Bot
              </Button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, hint }: {
  label: string; name: string; type?: string; defaultValue?: string; hint?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="field-label">{label}</label>
      <input type={type} name={name} defaultValue={defaultValue} className="field-input" />
      {hint && <div className="text-[9px] text-muted2">{hint}</div>}
    </div>
  )
}
