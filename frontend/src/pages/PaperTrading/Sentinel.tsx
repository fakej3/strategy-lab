import { useEffect, useState, useCallback } from 'react'
import {
  Activity, Plus, Square, RotateCcw, TrendingUp, TrendingDown,
  ChevronRight, X, Search, AlertTriangle, Zap, RefreshCw,
} from 'lucide-react'
import { botApi } from '../../api/bot'
import type { StrategyInstance, SentinelPortfolio, AvailableStrategy, InstanceStatus } from '../../types'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { cn } from '../../lib/cn'

// ── Constants ─────────────────────────────────────────────────────────────────

const QUICK_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'ADAUSDT', 'DOGEUSDT', 'XRPUSDT']
const INTERVALS     = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
const CAPITAL_PRESETS = [
  { label: '$1K',  value: 1000 },
  { label: '$5K',  value: 5000 },
  { label: '$10K', value: 10000 },
  { label: '$50K', value: 50000 },
]
const SCAN_DATE_PRESETS = [
  { label: '1M',  months: 1  },
  { label: '3M',  months: 3  },
  { label: '6M',  months: 6  },
  { label: '1Y',  months: 12 },
]

function monthsAgo(n: number): string {
  const d = new Date()
  d.setMonth(d.getMonth() - n)
  return d.toISOString().slice(0, 10)
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

// ── Instance badge ─────────────────────────────────────────────────────────────

function InstanceBadge({ status }: { status: InstanceStatus }) {
  if (status === 'running')
    return (
      <Badge variant="warn">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
        Running
      </Badge>
    )
  if (status === 'starting')
    return (
      <Badge variant="blue">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
        Starting
      </Badge>
    )
  if (status === 'failed')
    return <Badge variant="fail">Failed</Badge>
  return <Badge variant="muted">Stopped</Badge>
}

// ── PnL display ───────────────────────────────────────────────────────────────

function Pnl({ value, prefix = '' }: { value: number; prefix?: string }) {
  const pos = value >= 0
  return (
    <span className={cn('font-mono text-xs font-semibold tabular-nums', pos ? 'text-green' : 'text-red')}>
      {pos ? '+' : ''}{prefix}{value.toFixed(2)}
    </span>
  )
}

// ── Portfolio metric tile ─────────────────────────────────────────────────────

function MetricTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-5 py-3 border-r border-border last:border-r-0">
      <div className="text-[10px] font-semibold tracking-widest text-muted2 uppercase">{label}</div>
      <div className="text-lg font-semibold text-text tabular-nums leading-tight">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  )
}

// ── Instance card ─────────────────────────────────────────────────────────────

interface CardProps {
  inst: StrategyInstance
  onStop:    (id: string) => void
  onRestart: (id: string) => void
  busy:      boolean
}

function InstanceCard({ inst, onStop, onRestart, busy }: CardProps) {
  const totalPnl = inst.realized_pnl + inst.unrealized_pnl
  const hasPos   = !!inst.position
  const parts    = inst.instance_id.split(':')

  return (
    <div className={cn(
      'flex flex-col gap-3 p-4 rounded-xl border bg-surface transition-all',
      inst.status === 'failed'  && 'border-red/25 bg-red/4',
      inst.status === 'running' && 'border-border hover:border-border2',
      inst.status === 'stopped' && 'border-border/60 opacity-80',
      inst.status === 'starting'&& 'border-accent/25 bg-accent/4',
    )}>
      {/* Header row */}
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-bold text-text">
              {inst.symbol.replace('USDT', '')}/{inst.interval}
            </span>
            <InstanceBadge status={inst.status} />
          </div>
          <div className="text-xs text-muted mt-0.5 truncate" title={inst.strategy_name}>
            {inst.strategy_name}
            {parts.length > 3 && (
              <span className="text-muted2 ml-1 font-mono">
                · {parts.slice(3).join(' ')}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          <button
            onClick={() => onRestart(inst.instance_id)}
            disabled={busy || inst.status === 'starting'}
            title="Restart"
            className="p-1.5 rounded-md text-muted hover:text-text hover:bg-s2 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <RotateCcw size={12} />
          </button>
          <button
            onClick={() => onStop(inst.instance_id)}
            disabled={busy || inst.status === 'stopped' || inst.status === 'starting'}
            title="Stop"
            className="p-1.5 rounded-md text-muted hover:text-red hover:bg-red/8 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Square size={12} />
          </button>
        </div>
      </div>

      {/* Position row */}
      <div className="flex items-center gap-3 text-xs">
        {hasPos ? (
          <>
            <div className={cn(
              'flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold',
              inst.position!.direction === 'long' ? 'bg-green/10 text-green' : 'bg-red/10 text-red',
            )}>
              {inst.position!.direction === 'long' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              {inst.position!.direction.toUpperCase()}
            </div>
            <span className="font-mono text-muted2">
              {inst.position!.size.toFixed(5)} @ ${inst.position!.entry_price.toLocaleString()}
            </span>
          </>
        ) : (
          <span className="text-muted2">Flat</span>
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border/60">
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted2 uppercase tracking-wider">Total PnL</span>
          <Pnl value={totalPnl} prefix="$" />
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted2 uppercase tracking-wider">Unrealized</span>
          <Pnl value={inst.unrealized_pnl} prefix="$" />
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-muted2 uppercase tracking-wider">Trades</span>
          <span className="font-mono text-xs text-text">{inst.n_trades}</span>
        </div>
      </div>

      {/* Last signal / error */}
      {inst.status === 'failed' && inst.error ? (
        <div className="flex items-start gap-1.5 text-[11px] text-red bg-red/6 px-2.5 py-2 rounded-lg">
          <AlertTriangle size={10} className="shrink-0 mt-0.5" />
          <span className="line-clamp-2">{inst.error}</span>
        </div>
      ) : inst.last_signal ? (
        <div className="text-[11px] text-muted px-2.5 py-1.5 bg-s2 rounded-lg font-mono">
          Last: {inst.last_signal}
        </div>
      ) : null}
    </div>
  )
}

// ── Add Strategy Modal ────────────────────────────────────────────────────────

interface AddModalProps {
  strategies: AvailableStrategy[]
  onClose:   () => void
  onDeploy:  (spec: { symbol: string; interval: string; strategy_name: string; strategy_params: Record<string, unknown> }[], capital: number) => void
  deploying: boolean
}

function AddStrategyModal({ strategies, onClose, onDeploy, deploying }: AddModalProps) {
  const [step,         setStep]         = useState<1 | 2 | 3 | 4>(1)
  const [symbol,       setSymbol]       = useState('BTCUSDT')
  const [customSym,    setCustomSym]    = useState('')
  const [interval,     setInterval]     = useState('1h')
  const [stratName,    setStratName]    = useState(strategies[0]?.name ?? '')
  const [capital,      setCapital]      = useState(10000)
  const [useCustomCap, setUseCustomCap] = useState(false)
  const [customCap,    setCustomCap]    = useState('')

  const finalCap = useCustomCap ? (Number(customCap) || 0) : capital

  function deploy() {
    const strat = strategies.find(s => s.name === stratName)
    const params: Record<string, unknown> = {}
    if (strat?.params) {
      for (const p of strat.params) params[p.name] = p.default
    } else if (strat?.param_space) {
      for (const [k, vs] of Object.entries(strat.param_space)) {
        if (Array.isArray(vs) && vs.length > 0) params[k] = vs[0]
      }
    }
    onDeploy([{ symbol, interval, strategy_name: stratName, strategy_params: params }], finalCap)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md bg-bg border border-border rounded-2xl shadow-2xl flex flex-col max-h-[90vh]">

        {/* Title */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="text-sm font-bold text-text">Add Strategy Instance</div>
          <button onClick={onClose} className="text-muted hover:text-text transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-0 px-5 py-3 border-b border-border shrink-0">
          {(['Symbol', 'Timeframe', 'Strategy', 'Deploy'] as const).map((label, i) => {
            const n = (i + 1) as 1 | 2 | 3 | 4
            const active = step === n
            const done   = step > n
            return (
              <div key={label} className="flex items-center gap-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <div className={cn(
                    'w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center shrink-0',
                    active ? 'bg-accent text-bg' : done ? 'bg-green text-bg' : 'bg-s3 text-muted2',
                  )}>
                    {done ? '✓' : n}
                  </div>
                  <span className={cn('text-xs hidden sm:block', active ? 'text-text font-medium' : 'text-muted2')}>
                    {label}
                  </span>
                </div>
                {i < 3 && <ChevronRight size={12} className="text-border mx-1 flex-1" />}
              </div>
            )
          })}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {step === 1 && (
            <div className="flex flex-col gap-4">
              <div className="text-[10px] font-semibold tracking-widest text-muted2">SELECT SYMBOL</div>
              <div className="flex flex-wrap gap-2">
                {QUICK_SYMBOLS.map(sym => (
                  <button
                    key={sym}
                    onClick={() => setSymbol(sym)}
                    className={cn(
                      'px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border transition-all',
                      symbol === sym
                        ? 'bg-accent text-bg border-accent'
                        : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                    )}
                  >
                    {sym.replace('USDT', '')}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customSym}
                  onChange={e => setCustomSym(e.target.value.toUpperCase())}
                  onKeyDown={e => { if (e.key === 'Enter' && customSym) { setSymbol(customSym); setCustomSym('') } }}
                  placeholder="Custom symbol (e.g. XRPUSDT)"
                  className="field-input flex-1 text-xs font-mono"
                />
                <button
                  onClick={() => { if (customSym) { setSymbol(customSym); setCustomSym('') } }}
                  className="px-3 py-2 bg-s3 border border-border rounded-lg text-xs text-muted hover:text-text hover:border-border2 transition-colors"
                >
                  Use
                </button>
              </div>
              {symbol && (
                <div className="text-xs text-muted">
                  Selected: <span className="font-mono font-semibold text-accent">{symbol}</span>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="flex flex-col gap-4">
              <div className="text-[10px] font-semibold tracking-widest text-muted2">SELECT TIMEFRAME</div>
              <div className="flex gap-2 flex-wrap">
                {INTERVALS.map(iv => (
                  <button
                    key={iv}
                    onClick={() => setInterval(iv)}
                    className={cn(
                      'px-4 py-2 rounded-lg text-sm font-mono font-semibold border transition-all',
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
          )}

          {step === 3 && (
            <div className="flex flex-col gap-3">
              <div className="text-[10px] font-semibold tracking-widest text-muted2">SELECT STRATEGY</div>
              {strategies.length === 0 ? (
                <div className="text-sm text-muted py-4 text-center">No strategies available</div>
              ) : strategies.map(s => (
                <button
                  key={s.name}
                  onClick={() => setStratName(s.name)}
                  className={cn(
                    'flex items-center gap-3 w-full text-left px-4 py-3 rounded-xl border transition-all',
                    stratName === s.name
                      ? 'border-accent/40 bg-accent/8 ring-1 ring-accent/20'
                      : 'border-border bg-surface hover:border-border2 hover:bg-s2',
                  )}
                >
                  <div className={cn(
                    'w-2 h-2 rounded-full shrink-0',
                    stratName === s.name ? 'bg-accent' : 'bg-muted2',
                  )} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text">{s.name}</div>
                    <div className="text-xs text-muted mt-0.5 font-mono">
                      {s.params?.length ?? (s.param_space ? Object.keys(s.param_space).length : 0)} params
                    </div>
                  </div>
                  {stratName === s.name && (
                    <span className="text-[11px] font-bold text-accent px-2 py-0.5 bg-accent/10 rounded-full shrink-0">Selected</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {step === 4 && (
            <div className="flex flex-col gap-4">
              <div className="text-[10px] font-semibold tracking-widest text-muted2">REVIEW & DEPLOY</div>
              <table className="w-full text-xs">
                <tbody>
                  {[
                    { l: 'Symbol',    v: symbol },
                    { l: 'Timeframe', v: interval },
                    { l: 'Strategy',  v: stratName || '—' },
                    { l: 'Mode',      v: 'Paper (Simulation)' },
                  ].map(({ l, v }) => (
                    <tr key={l} className="border-b border-border/50">
                      <td className="py-2 text-muted2 pr-3 w-[90px]">{l}</td>
                      <td className="py-2 text-text font-mono text-[11px]">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="flex flex-col gap-2">
                <div className="text-[10px] font-semibold tracking-widest text-muted2">CAPITAL</div>
                <div className="flex gap-1.5 flex-wrap">
                  {CAPITAL_PRESETS.map(p => (
                    <button
                      key={p.value}
                      onClick={() => { setCapital(p.value); setUseCustomCap(false) }}
                      className={cn(
                        'px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border transition-all',
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
                      'px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all',
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
                    value={customCap}
                    onChange={e => setCustomCap(e.target.value)}
                    placeholder="Amount in USD"
                    min="1"
                    className="field-input text-sm font-mono"
                    autoFocus
                  />
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-border shrink-0">
          <Button variant="ghost" size="sm" onClick={step > 1 ? () => setStep(s => (s - 1) as 1 | 2 | 3 | 4) : onClose}>
            {step === 1 ? 'Cancel' : '← Back'}
          </Button>
          {step < 4 ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setStep(s => (s + 1) as 1 | 2 | 3 | 4)}
              disabled={step === 3 && !stratName}
            >
              Next →
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={deploy}
              loading={deploying}
              disabled={!stratName || finalCap < 1}
            >
              <Zap size={12} />
              Deploy Instance
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Research Scanner ──────────────────────────────────────────────────────────

interface ScanJob {
  job_id:   string
  symbol:   string
  interval: string
  strategy: string
}

function ResearchScanner({ strategies }: { strategies: AvailableStrategy[] }) {
  const [scanSymbols,  setScanSymbols]  = useState<string[]>(['BTCUSDT', 'ETHUSDT'])
  const [scanIntervals,setScanIntervals]= useState<string[]>(['1h'])
  const [scanStrats,   setScanStrats]   = useState<string[]>(strategies.slice(0, 1).map(s => s.name))
  const [datePreset,   setDatePreset]   = useState(3)
  const [scanning,     setScanning]     = useState(false)
  const [scanJobs,     setScanJobs]     = useState<ScanJob[]>([])
  const [scanErr,      setScanErr]      = useState('')
  const [customSym,    setCustomSym]    = useState('')

  function toggleArr<T>(arr: T[], item: T): T[] {
    return arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item]
  }

  async function runScan() {
    if (!scanSymbols.length || !scanIntervals.length || !scanStrats.length) {
      setScanErr('Select at least one symbol, interval, and strategy.')
      return
    }
    setScanErr('')
    setScanning(true)
    setScanJobs([])
    try {
      const res = await botApi.scan({
        symbols:    scanSymbols,
        intervals:  scanIntervals,
        strategies: scanStrats,
        start_date: monthsAgo(datePreset),
        end_date:   today(),
        capital:    10000,
      })
      setScanJobs(res.jobs ?? [])
    } catch (ex) {
      setScanErr(ex instanceof Error ? ex.message : String(ex))
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-5 border-t border-border bg-surface">
      <div className="flex items-center gap-2">
        <Search size={13} className="text-muted2" />
        <span className="text-[11px] font-semibold tracking-widest text-muted2 uppercase">Research Scanner</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        {/* Symbol universe */}
        <div className="flex flex-col gap-2">
          <div className="text-[10px] font-semibold tracking-widest text-muted2">SYMBOLS</div>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_SYMBOLS.map(sym => {
              const on = scanSymbols.includes(sym)
              return (
                <button
                  key={sym}
                  onClick={() => setScanSymbols(toggleArr(scanSymbols, sym))}
                  className={cn(
                    'px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border transition-all',
                    on ? 'bg-accent text-bg border-accent' : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                  )}
                >
                  {sym.replace('USDT', '')}
                </button>
              )
            })}
          </div>
          <div className="flex gap-1.5">
            <input
              type="text"
              value={customSym}
              onChange={e => setCustomSym(e.target.value.toUpperCase())}
              onKeyDown={e => {
                if (e.key === 'Enter' && customSym) {
                  setScanSymbols(prev => prev.includes(customSym) ? prev : [...prev, customSym])
                  setCustomSym('')
                }
              }}
              placeholder="Add symbol…"
              className="field-input flex-1 text-[11px] font-mono"
            />
          </div>
        </div>

        {/* Timeframe */}
        <div className="flex flex-col gap-2">
          <div className="text-[10px] font-semibold tracking-widest text-muted2">TIMEFRAMES</div>
          <div className="flex flex-wrap gap-1.5">
            {INTERVALS.map(iv => {
              const on = scanIntervals.includes(iv)
              return (
                <button
                  key={iv}
                  onClick={() => setScanIntervals(toggleArr(scanIntervals, iv))}
                  className={cn(
                    'px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border transition-all',
                    on ? 'bg-accent text-bg border-accent' : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                  )}
                >
                  {iv}
                </button>
              )
            })}
          </div>
          <div className="flex flex-col gap-1.5 mt-1">
            <div className="text-[10px] font-semibold tracking-widest text-muted2">LOOKBACK</div>
            <div className="flex gap-1.5">
              {SCAN_DATE_PRESETS.map(p => (
                <button
                  key={p.months}
                  onClick={() => setDatePreset(p.months)}
                  className={cn(
                    'px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border transition-all',
                    datePreset === p.months
                      ? 'bg-accent text-bg border-accent'
                      : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Strategies */}
        <div className="flex flex-col gap-2">
          <div className="text-[10px] font-semibold tracking-widest text-muted2">STRATEGIES</div>
          <div className="flex flex-col gap-1.5 max-h-32 overflow-y-auto scrollbar-thin">
            {strategies.map(s => {
              const on = scanStrats.includes(s.name)
              return (
                <button
                  key={s.name}
                  onClick={() => setScanStrats(toggleArr(scanStrats, s.name))}
                  className={cn(
                    'flex items-center gap-2 w-full text-left px-3 py-1.5 rounded-lg border text-[11px] transition-all',
                    on ? 'border-accent/40 bg-accent/8 text-accent' : 'border-border bg-s2 text-muted hover:border-border2 hover:text-text',
                  )}
                >
                  <div className={cn('w-1.5 h-1.5 rounded-full shrink-0', on ? 'bg-accent' : 'bg-muted2')} />
                  <span className="font-mono truncate">{s.name}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Scan footer */}
      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          size="sm"
          onClick={runScan}
          loading={scanning}
          disabled={scanning}
        >
          <Search size={12} />
          {scanning ? 'Scanning…' : 'Run Scan'}
        </Button>
        {scanErr && (
          <span className="text-xs text-red">{scanErr}</span>
        )}
        {scanJobs.length > 0 && !scanning && (
          <span className="text-xs text-muted">{scanJobs.length} jobs queued</span>
        )}
      </div>

      {/* Jobs table */}
      {scanJobs.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-s2">
                <th className="px-3 py-2 text-left text-[10px] font-semibold tracking-widest text-muted2">JOB ID</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold tracking-widest text-muted2">SYMBOL</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold tracking-widest text-muted2">INTERVAL</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold tracking-widest text-muted2">STRATEGY</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold tracking-widest text-muted2">STATUS</th>
              </tr>
            </thead>
            <tbody>
              {scanJobs.map(job => (
                <tr key={job.job_id} className="border-b border-border/50 last:border-0 hover:bg-s2/50 transition-colors">
                  <td className="px-3 py-2 font-mono text-[11px] text-muted2">{job.job_id.slice(0, 8)}…</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-text">{job.symbol}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-text">{job.interval}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-text">{job.strategy}</td>
                  <td className="px-3 py-2"><Badge variant="pending">Queued</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main SENTINEL page ────────────────────────────────────────────────────────

interface Props {
  strategies: AvailableStrategy[]
}

export function Sentinel({ strategies }: Props) {
  const [instances,   setInstances]   = useState<StrategyInstance[]>([])
  const [portfolio,   setPortfolio]   = useState<SentinelPortfolio | null>(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState('')
  const [showAdd,     setShowAdd]     = useState(false)
  const [deploying,   setDeploying]   = useState(false)
  const [busyId,      setBusyId]      = useState<string | null>(null)
  const [showScanner, setShowScanner] = useState(false)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [insts, port] = await Promise.all([
        botApi.instances(),
        botApi.portfolio(),
      ])
      setInstances(insts)
      setPortfolio(port)
      setError('')
    } catch (ex) {
      if (!silent) setError(ex instanceof Error ? ex.message : String(ex))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(() => load(true), 4000)
    return () => clearInterval(id)
  }, [load])

  async function stopInstance(id: string) {
    setBusyId(id)
    try { await botApi.stopInstance(id); await load(true) }
    catch { /* ignore */ }
    finally { setBusyId(null) }
  }

  async function restartInstance(id: string) {
    setBusyId(id)
    try { await botApi.restartInstance(id); await load(true) }
    catch { /* ignore */ }
    finally { setBusyId(null) }
  }

  async function stopAll() {
    const running = instances.filter(i => i.status === 'running' || i.status === 'starting')
    for (const inst of running) {
      try { await botApi.stopInstance(inst.instance_id) } catch { /* ignore */ }
    }
    await load(true)
  }

  async function restartFailed() {
    const failed = instances.filter(i => i.status === 'failed')
    for (const inst of failed) {
      try { await botApi.restartInstance(inst.instance_id) } catch { /* ignore */ }
    }
    await load(true)
  }

  async function deployInstances(
    specs: { symbol: string; interval: string; strategy_name: string; strategy_params: Record<string, unknown> }[],
    capital: number,
  ) {
    setDeploying(true)
    try {
      await botApi.startInstances({ specs, capital })
      setShowAdd(false)
      await load(true)
    } catch { /* ignore */ }
    finally { setDeploying(false) }
  }

  const nRunning = instances.filter(i => i.status === 'running').length
  const nFailed  = instances.filter(i => i.status === 'failed').length

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-bg">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-accent/40 border-t-accent rounded-full animate-spin" />
          <span className="text-xs text-muted">Connecting to SENTINEL…</span>
        </div>
      </div>
    )
  }

  if (error && !portfolio) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 bg-bg px-6">
        <AlertTriangle size={28} className="text-red/60" />
        <div className="text-sm text-red text-center">{error}</div>
        <Button variant="secondary" size="sm" onClick={() => load()}>
          <RefreshCw size={12} /> Retry
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-bg overflow-hidden">

      {/* Status bar */}
      <div className="flex items-center gap-3 px-5 h-10 bg-surface border-b border-border shrink-0">
        <Activity size={13} className="text-accent" />
        <span className="text-sm font-bold text-text">SENTINEL</span>
        <span className="text-muted2 text-xs">·</span>
        <span className="text-xs text-muted2">{instances.length} instance{instances.length !== 1 ? 's' : ''}</span>
        {nRunning > 0 && (
          <>
            <span className="text-muted2 text-xs">·</span>
            <span className="flex items-center gap-1.5 text-xs text-amber">
              <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
              {nRunning} running
            </span>
          </>
        )}
        {nFailed > 0 && (
          <>
            <span className="text-muted2 text-xs">·</span>
            <span className="text-xs text-red">{nFailed} failed</span>
          </>
        )}
        <span className="ml-auto text-xs text-muted2 font-mono">Simulation only · No real funds</span>
      </div>

      {/* Portfolio header */}
      {portfolio && (
        <div className="flex items-stretch bg-surface border-b border-border shrink-0 overflow-x-auto">
          <MetricTile
            label="Equity"
            value={`$${portfolio.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            sub={`Capital: $${portfolio.capital.toLocaleString()}`}
          />
          <MetricTile
            label="Today's P&L"
            value={<Pnl value={portfolio.realized_pnl + portfolio.unrealized_pnl} prefix="$" />}
            sub={`Realized: $${portfolio.realized_pnl.toFixed(2)}`}
          />
          <MetricTile
            label="Available"
            value={`$${portfolio.cash.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            sub="Available cash"
          />
          <MetricTile
            label="Instances"
            value={portfolio.n_instances}
            sub={`${portfolio.n_running} running · ${portfolio.n_failed} failed`}
          />
        </div>
      )}

      {/* Top controls */}
      <div className="flex items-center gap-2 px-5 py-3 bg-surface border-b border-border shrink-0 flex-wrap">
        <Button variant="primary" size="sm" onClick={() => setShowAdd(true)}>
          <Plus size={12} />
          Add Strategy
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={stopAll}
          disabled={nRunning === 0}
        >
          <Square size={12} />
          Stop All
        </Button>
        {nFailed > 0 && (
          <Button variant="secondary" size="sm" onClick={restartFailed}>
            <RotateCcw size={12} />
            Restart Failed ({nFailed})
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowScanner(v => !v)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-all font-semibold',
              showScanner
                ? 'bg-accent/10 text-accent border-accent/30'
                : 'bg-s2 text-muted border-border hover:border-border2 hover:text-text',
            )}
          >
            <Search size={11} />
            Research Scanner
          </button>
          <button
            onClick={() => load(true)}
            className="p-1.5 text-muted hover:text-text hover:bg-s2 rounded-md transition-colors"
            title="Refresh"
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">

        {/* Instance grid */}
        {instances.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 gap-4 text-center px-6">
            <div className="w-10 h-10 rounded-xl bg-s2 flex items-center justify-center">
              <Activity size={18} className="text-muted2" />
            </div>
            <div>
              <div className="text-sm font-semibold text-text mb-1">No instances running</div>
              <div className="text-xs text-muted">Add a strategy instance to start paper trading</div>
            </div>
            <Button variant="primary" size="sm" onClick={() => setShowAdd(true)}>
              <Plus size={12} />
              Add Strategy
            </Button>
          </div>
        ) : (
          <div className="p-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {instances.map(inst => (
                <InstanceCard
                  key={inst.instance_id}
                  inst={inst}
                  onStop={stopInstance}
                  onRestart={restartInstance}
                  busy={busyId === inst.instance_id}
                />
              ))}
            </div>
          </div>
        )}

        {/* Research scanner */}
        {showScanner && (
          <ResearchScanner strategies={strategies} />
        )}
      </div>

      {/* Add Strategy modal */}
      {showAdd && (
        <AddStrategyModal
          strategies={strategies}
          onClose={() => setShowAdd(false)}
          onDeploy={deployInstances}
          deploying={deploying}
        />
      )}
    </div>
  )
}
