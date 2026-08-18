import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CandlestickChart, TrendingUp, FlaskConical, List, LayoutGrid } from 'lucide-react'
import { Link } from 'react-router-dom'
import { strategiesApi } from '../api/strategies'
import { LoadingState } from '../components/ui/EmptyState'
import { fmt } from '../lib/format'
import { cn } from '../lib/cn'
import type { StrategyResult } from '../types'

const METRICS = ['sharpe_ratio', 'cagr', 'win_rate', 'profit_factor', 'total_return', 'max_drawdown_pct']
const METRIC_LABELS: Record<string, string> = {
  sharpe_ratio:     'Sharpe',
  cagr:             'CAGR',
  win_rate:         'Win Rate',
  profit_factor:    'P-Factor',
  total_return:     'Return',
  max_drawdown_pct: 'Max DD',
}

type ViewMode = 'grid' | 'list'

function gateVariant(gate: string): { label: string; color: string; bg: string; dot: string } {
  const g = gate.toUpperCase()
  if (g === 'PROMISING')
    return { label: 'Promising', color: 'text-green', bg: 'bg-green/10 border-green/20', dot: 'bg-green' }
  if (g.includes('IMPROVEMENT') || g === 'NEEDS_IMPROVEMENT')
    return { label: 'Needs Work', color: 'text-amber', bg: 'bg-amber/10 border-amber/20', dot: 'bg-amber' }
  return { label: 'Rejected', color: 'text-muted', bg: 'bg-s3 border-border', dot: 'bg-muted2' }
}

function SharpeBar({ value, max }: { value: number | null; max: number }) {
  if (value == null || max <= 0) return <span className="text-muted">—</span>
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  const color = value >= 1.5 ? 'bg-green' : value >= 0.8 ? 'bg-amber' : 'bg-red'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="font-mono tabular-nums text-sm text-text shrink-0">{fmt(value, 2)}</span>
      <div className="flex-1 h-1 bg-s3 rounded-full overflow-hidden min-w-[32px]">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** Deterministic pseudo-sparkline from strategy metrics. */
function MiniSparkline({ sharpe, cagr, dd }: { sharpe: number | null; cagr: number | null; dd: number | null }) {
  const s  = sharpe ?? 0
  const c  = cagr   ?? 0
  const positive = c > 0

  // Generate a plausible-looking equity path from the metrics
  const pts: [number, number][] = []
  const N = 20
  let y = 50
  for (let i = 0; i <= N; i++) {
    const trend = (c / N) * 800
    const vol   = Math.max(0.5, (Math.abs(dd ?? 0.1) * 300) / Math.sqrt(Math.max(s, 0.5)))
    const rand  = Math.sin(i * 2.7 + s * 3) * vol + Math.cos(i * 1.3 + c * 5) * vol * 0.5
    y = Math.max(5, Math.min(75, y + trend + rand))
    pts.push([i * (280 / N), y])
  }

  const d   = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ')
  const fill = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ')
        + ` L${pts[pts.length-1][0]},80 L0,80 Z`

  const stroke = positive ? '#34D399' : '#F87171'
  const fillId = `spark-${Math.round((sharpe ?? 0) * 100)}-${Math.round((cagr ?? 0) * 100)}`

  return (
    <svg viewBox="0 0 280 80" preserveAspectRatio="none" style={{ width: '100%', height: '48px' }}>
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={fill} fill={`url(#${fillId})`} />
      <path d={d} fill="none" stroke={stroke} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function MetricPill({
  label, value, color,
}: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] font-semibold text-muted uppercase tracking-wider mb-0.5">{label}</span>
      <span className={cn('text-sm font-mono font-semibold tabular-nums', color ?? 'text-text')}>{value}</span>
    </div>
  )
}

function StrategyCard({ r, maxSharpe, onTrade }: { r: StrategyResult; maxSharpe: number; onTrade: () => void }) {
  const gate = gateVariant(r.gate_decision)
  return (
    <div className="bg-surface border border-border rounded-xl p-5 flex flex-col gap-4 hover:border-border2 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-text truncate">{r.strategy_class}</div>
          <div className="text-xs text-muted font-mono mt-0.5">
            {r.symbol} <span className="text-muted2">·</span> {r.interval}
          </div>
        </div>
        <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold border shrink-0', gate.bg, gate.color)}>
          <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', gate.dot)} />
          {gate.label}
        </span>
      </div>

      {/* Sparkline */}
      <div className="-mx-1">
        <MiniSparkline sharpe={r.sharpe_ratio} cagr={r.cagr} dd={r.max_drawdown_pct} />
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-2">
        <MetricPill
          label="Sharpe"
          value={r.sharpe_ratio != null ? fmt(r.sharpe_ratio, 2) : '—'}
          color={r.sharpe_ratio != null && r.sharpe_ratio >= 1.5 ? 'text-green' : r.sharpe_ratio != null && r.sharpe_ratio >= 0.8 ? 'text-amber' : 'text-red'}
        />
        <MetricPill
          label="CAGR"
          value={r.cagr != null ? fmt(r.cagr, 1, true) : '—'}
          color={(r.cagr ?? 0) > 0 ? 'text-green' : 'text-red'}
        />
        <MetricPill
          label="Max DD"
          value={r.max_drawdown_pct != null ? fmt(r.max_drawdown_pct, 1, true) : '—'}
          color="text-red"
        />
        <MetricPill
          label="Win %"
          value={r.win_rate != null ? fmt(r.win_rate, 1, true) : '—'}
        />
      </div>

      {/* Sharpe bar */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-muted uppercase tracking-wider w-12 shrink-0">Sharpe</span>
        <div className="flex-1 h-1 bg-s3 rounded-full overflow-hidden">
          <div
            className={cn(
              'h-full rounded-full',
              (r.sharpe_ratio ?? 0) >= 1.5 ? 'bg-green' : (r.sharpe_ratio ?? 0) >= 0.8 ? 'bg-amber' : 'bg-red',
            )}
            style={{ width: `${maxSharpe > 0 ? Math.min(100, ((r.sharpe_ratio ?? 0) / maxSharpe) * 100) : 0}%` }}
          />
        </div>
        <span className="text-[10px] text-muted2 font-mono w-8 text-right shrink-0">{r.total_trades}t</span>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-border">
        <button
          onClick={onTrade}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md bg-green/10 border border-green/20 text-green text-xs font-semibold hover:bg-green/15 hover:border-green/30 transition-colors"
        >
          <CandlestickChart size={12} />
          Deploy to Paper
        </button>
        <button
          onClick={onTrade}
          className="p-1.5 rounded-md bg-s3 border border-border text-muted hover:text-text hover:border-border2 transition-colors"
          title="P-Factor"
        >
          <span className="text-[11px] font-mono">{r.profit_factor != null ? fmt(r.profit_factor, 2) : '—'}</span>
          <span className="text-[10px] text-muted2 ml-0.5">pf</span>
        </button>
      </div>
    </div>
  )
}

export function Strategies() {
  const navigate   = useNavigate()
  const [results,  setResults]  = useState<StrategyResult[]>([])
  const [metric,   setMetric]   = useState('sharpe_ratio')
  const [decision, setDec]      = useState('')
  const [loading,  setLoading]  = useState(true)
  const [view,     setView]     = useState<ViewMode>('grid')

  useEffect(() => {
    setLoading(true)
    strategiesApi.list(metric, 100)
      .then(r => setResults(decision ? r.filter(x => x.gate_decision.toUpperCase() === decision.toUpperCase()) : r))
      .finally(() => setLoading(false))
  }, [metric, decision])

  const maxSharpe = results.reduce((m, r) => Math.max(m, r.sharpe_ratio ?? 0), 0)

  const counts = {
    all:        results.length,
    promising:  results.filter(r => r.gate_decision.toUpperCase() === 'PROMISING').length,
    needsWork:  results.filter(r => r.gate_decision.toUpperCase().includes('IMPROVEMENT')).length,
    rejected:   results.filter(r => r.gate_decision.toUpperCase() === 'REJECT').length,
  }

  function tradeLink(r: StrategyResult) {
    const params = new URLSearchParams({ symbol: r.symbol, interval: r.interval, strategy: r.strategy_class })
    navigate(`/paper-trading?${params}`)
  }

  const FILTERS = [
    { value: '',              label: 'All',       count: counts.all },
    { value: 'PROMISING',     label: 'Promising', count: counts.promising },
    { value: 'NEEDS IMPROVEMENT', label: 'Needs Work', count: counts.needsWork },
    { value: 'REJECT',        label: 'Rejected',  count: counts.rejected },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="page-header">
        <span className="page-title">Strategies</span>
        <div className="flex items-center gap-3">
          <select
            value={metric}
            onChange={e => setMetric(e.target.value)}
            className="field-select text-sm py-1 px-2.5 h-8"
          >
            {METRICS.map(m => <option key={m} value={m}>{METRIC_LABELS[m] ?? m}</option>)}
          </select>
          <div className="flex items-center bg-s2 border border-border rounded-md p-0.5">
            <button
              onClick={() => setView('grid')}
              className={cn('p-1.5 rounded transition-colors', view === 'grid' ? 'bg-s3 text-text' : 'text-muted hover:text-text')}
            >
              <LayoutGrid size={14} />
            </button>
            <button
              onClick={() => setView('list')}
              className={cn('p-1.5 rounded transition-colors', view === 'list' ? 'bg-s3 text-text' : 'text-muted hover:text-text')}
            >
              <List size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-border">
        {FILTERS.map(f => (
          <button
            key={f.value}
            onClick={() => setDec(f.value)}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border transition-colors',
              decision === f.value
                ? 'bg-accent-bg border-accent/30 text-accent'
                : 'bg-surface border-border text-muted hover:text-text hover:border-border2',
            )}
          >
            {f.label}
            <span className={cn(
              'inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-semibold',
              decision === f.value ? 'bg-accent/20 text-accent' : 'bg-s3 text-muted2',
            )}>
              {f.count}
            </span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <LoadingState />}

        {!loading && results.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-24">
            <div className="w-14 h-14 rounded-full bg-s2 border border-border flex items-center justify-center">
              <FlaskConical size={22} className="text-muted2" />
            </div>
            <div className="text-center">
              <p className="text-base font-semibold text-text">No results found</p>
              <p className="text-sm text-muted mt-1">
                {decision ? 'Try clearing the filter.' : 'Run a research session to generate strategy results.'}
              </p>
            </div>
            {!decision && (
              <Link
                to="/research"
                className="inline-flex items-center gap-2 px-5 py-2 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors"
              >
                <FlaskConical size={14} />
                Start Research
              </Link>
            )}
          </div>
        )}

        {!loading && results.length > 0 && (
          <>
            {view === 'grid' ? (
              <div className="p-6">
                <div className="grid grid-cols-3 gap-4 max-w-7xl">
                  {results.map(r => (
                    <StrategyCard key={r.id} r={r} maxSharpe={maxSharpe} onTrade={() => tradeLink(r)} />
                  ))}
                </div>
              </div>
            ) : (
              <table className="w-full table-dense">
                <thead>
                  <tr className="bg-surface border-b border-border sticky top-0 z-10">
                    <th className="w-10"></th>
                    <th>Strategy</th>
                    <th>Market</th>
                    <th className="text-right">Sharpe</th>
                    <th className="text-right">CAGR</th>
                    <th className="text-right">Max DD</th>
                    <th className="text-right">Win %</th>
                    <th className="text-right">P-Factor</th>
                    <th className="text-right">Trades</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {results.map(r => {
                    const gate = gateVariant(r.gate_decision)
                    return (
                      <tr key={r.id} className="border-b border-border hover:bg-s2 transition-colors">
                        <td>
                          <div className={cn('w-1.5 h-1.5 rounded-full mx-auto', gate.dot)} />
                        </td>
                        <td>
                          <div className="font-semibold text-text text-sm">{r.strategy_class}</div>
                          <div className="text-xs text-muted2 font-mono mt-0.5 truncate max-w-[180px]" title={r.params}>
                            {r.params?.slice(0, 40)}{(r.params?.length ?? 0) > 40 && '…'}
                          </div>
                        </td>
                        <td>
                          <span className="font-mono text-sm text-muted">{r.symbol}</span>
                          <span className="text-muted2 mx-1">·</span>
                          <span className="font-mono text-sm text-muted">{r.interval}</span>
                        </td>
                        <td className="text-right">
                          <SharpeBar value={r.sharpe_ratio} max={maxSharpe} />
                        </td>
                        <td className={cn('text-right font-mono text-sm', (r.cagr ?? 0) > 0 ? 'text-green' : 'text-red')}>
                          {fmt(r.cagr, 2, true)}
                        </td>
                        <td className="text-right font-mono text-sm text-red">
                          {fmt(r.max_drawdown_pct, 2, true)}
                        </td>
                        <td className="text-right font-mono text-sm text-text">
                          {fmt(r.win_rate, 1, true)}
                        </td>
                        <td className="text-right font-mono text-sm text-text">
                          {fmt(r.profit_factor, 2)}
                        </td>
                        <td className="text-right font-mono text-sm text-muted">
                          {r.total_trades}
                        </td>
                        <td>
                          <div className="flex items-center gap-1 justify-end">
                            <span className={cn('text-xs font-semibold', gate.color)}>{gate.label}</span>
                            <button
                              onClick={() => tradeLink(r)}
                              title="Deploy to Paper Trading"
                              className="ml-2 p-1.5 rounded text-muted hover:text-accent hover:bg-accent-bg transition-colors"
                            >
                              <CandlestickChart size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}

            <div className="flex items-center gap-3 px-6 py-3 border-t border-border text-xs text-muted">
              <TrendingUp size={12} />
              {results.length} result{results.length !== 1 ? 's' : ''}
              {decision && ` · filtered by ${decision.toLowerCase()}`}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
