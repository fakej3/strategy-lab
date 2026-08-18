import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CandlestickChart, TrendingUp } from 'lucide-react'
import { strategiesApi } from '../api/strategies'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
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

function GateStripe({ gate }: { gate: string }) {
  const g = gate.toUpperCase()
  if (g === 'PROMISING')
    return <span className="text-xs font-semibold text-green">Promising</span>
  if (g.includes('IMPROVEMENT') || g === 'NEEDS_IMPROVEMENT')
    return <span className="text-xs font-semibold text-amber">Needs Work</span>
  return <span className="text-xs font-semibold text-muted">Rejected</span>
}

function SharpeBar({ value, max }: { value: number | null; max: number }) {
  if (value == null || max <= 0) return <span className="text-muted">—</span>
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  const color = value >= 1.5 ? 'bg-green' : value >= 0.8 ? 'bg-amber' : 'bg-red'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="font-mono tabular-nums text-sm text-text shrink-0">{fmt(value, 2)}</span>
      <div className="flex-1 h-1 bg-s3 rounded-full overflow-hidden min-w-[32px]">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function Strategies() {
  const navigate  = useNavigate()
  const [results, setResults] = useState<StrategyResult[]>([])
  const [metric,  setMetric]  = useState('sharpe_ratio')
  const [decision,setDec]     = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    strategiesApi.list(metric, 100)
      .then(r => setResults(decision ? r.filter(x => x.gate_decision.toUpperCase() === decision.toUpperCase()) : r))
      .finally(() => setLoading(false))
  }, [metric, decision])

  const maxSharpe = results.reduce((m, r) => Math.max(m, r.sharpe_ratio ?? 0), 0)

  function tradeLink(r: StrategyResult) {
    const params = new URLSearchParams({
      symbol: r.symbol,
      interval: r.interval,
      strategy: r.strategy_class,
    })
    navigate(`/paper-trading?${params}`)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Strategies</span>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="field-label">Sort by</label>
            <select
              value={metric}
              onChange={e => setMetric(e.target.value)}
              className="field-select text-sm py-1 px-2.5"
            >
              {METRICS.map(m => <option key={m} value={m}>{METRIC_LABELS[m] ?? m}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="field-label">Gate</label>
            <select
              value={decision}
              onChange={e => setDec(e.target.value)}
              className="field-select text-sm py-1 px-2.5"
            >
              <option value="">All</option>
              <option value="PROMISING">Promising</option>
              <option value="NEEDS IMPROVEMENT">Needs Work</option>
              <option value="REJECT">Rejected</option>
            </select>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <LoadingState />}

        {!loading && results.length === 0 && (
          <div className="p-6">
            <EmptyState
              message="No results found."
              sub="Run a research session to generate strategy results."
              action={
                <Link to="/research" className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors">
                  Start Research
                </Link>
              }
            />
          </div>
        )}

        {!loading && results.length > 0 && (
          <>
            <table className="w-full table-dense">
              <thead>
                <tr className="bg-surface border-b border-border sticky top-0 z-10">
                  <th className="w-10">Gate</th>
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
                {results.map(r => (
                  <tr key={r.id} className="border-b border-border hover:bg-s2 transition-colors">
                    <td>
                      <div className={cn(
                        'w-1.5 h-1.5 rounded-full mx-auto',
                        r.gate_decision.toUpperCase() === 'PROMISING' ? 'bg-green' :
                        r.gate_decision.toUpperCase().includes('IMPROVEMENT') ? 'bg-amber' : 'bg-muted2',
                      )} />
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
                        <GateStripe gate={r.gate_decision} />
                        <button
                          onClick={() => tradeLink(r)}
                          title="Launch in Paper Trading"
                          className="ml-2 p-1.5 rounded text-muted hover:text-accent hover:bg-accent-bg transition-colors"
                        >
                          <CandlestickChart size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center gap-3 px-4 py-3 border-t border-border text-xs text-muted">
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
