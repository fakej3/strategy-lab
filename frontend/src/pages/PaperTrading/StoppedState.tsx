import { useState, FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CandlestickChart } from 'lucide-react'
import { botApi } from '../../api/bot'
import { Button } from '../../components/ui/Button'
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

  // Pre-fill from "Trade this" link: ?symbol=X&interval=Y&strategy=Z
  const prefillSymbol   = searchParams.get('symbol')   ?? 'BTCUSDT'
  const prefillInterval = searchParams.get('interval') ?? '1h'
  const prefillStrategy = searchParams.get('strategy') ?? ''

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

  const hasPrefill = searchParams.has('symbol') || searchParams.has('strategy')

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-6 h-12 bg-surface border-b border-border shrink-0">
        <span className="w-2 h-2 rounded-full bg-muted2" />
        <span className="text-sm font-semibold text-muted">Paper Trading · Stopped</span>
        <span className="ml-auto text-xs text-muted2 font-mono">No real funds used</span>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {err && (
          <div className="px-4 py-3 mb-5 border border-red/20 bg-red/8 rounded-lg text-red text-sm">{err}</div>
        )}

        {hasPrefill && (
          <div className="flex items-center gap-3 px-4 py-3 mb-5 border border-accent/20 bg-accent-bg rounded-lg">
            <CandlestickChart size={15} className="text-accent shrink-0" />
            <div className="text-sm">
              <span className="text-accent font-semibold">Strategy pre-loaded from research results — </span>
              <span className="text-muted">review the configuration and click Start Bot.</span>
            </div>
          </div>
        )}

        <form id="botcfg" onSubmit={submit}>
          <div className="grid grid-cols-[1fr_260px] gap-5">
            <div className="bg-surface border border-border rounded-lg overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border">
                <span className="text-xs font-semibold text-muted">Configuration</span>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-3 gap-4 mb-4">
                  <Field label="Capital (USDT)" name="capital"   type="number" defaultValue="200" />
                  <Field label="Symbol(s)"      name="symbols"   defaultValue={prefillSymbol} hint="Comma-separated" />
                  <Field label="Interval(s)"    name="intervals" defaultValue={prefillInterval} hint="e.g. 1m, 1h, 4h" />
                </div>
                <div className="flex items-end gap-4">
                  <div className="flex flex-col gap-1.5 flex-1">
                    <label className="field-label">Strategy</label>
                    <select name="strategy" defaultValue={prefillStrategy || undefined} className="field-select w-full">
                      {strategies.map(s => (
                        <option key={s.name} value={s.name}>{s.name}</option>
                      ))}
                    </select>
                  </div>
                  <label className="flex items-center gap-2 cursor-pointer pb-0.5">
                    <input type="checkbox" name="recover" defaultChecked className="w-3.5 h-3.5 accent-amber shrink-0" />
                    <span className="text-sm text-muted">Recover open orders</span>
                  </label>
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-4">
              <div className="bg-surface border border-accent/20 rounded-lg px-4 py-4">
                <div className="text-accent font-semibold text-sm mb-2">Paper Trading</div>
                <div className="text-xs text-muted leading-relaxed">
                  No real funds used. Capital is simulated USDT. No Binance API key required. Trades execute against live market data.
                </div>
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
    <div className="flex flex-col gap-1.5">
      <label className="field-label">{label}</label>
      <input type={type} name={name} defaultValue={defaultValue} className="field-input" />
      {hint && <div className="text-xs text-muted2">{hint}</div>}
    </div>
  )
}
