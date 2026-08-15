import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { strategiesApi } from '../api/strategies'
import { StatusBadge } from '../components/ui/Badge'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmt } from '../lib/format'
import type { StrategyResult } from '../types'

const METRICS = ['sharpe_ratio', 'cagr', 'win_rate', 'profit_factor', 'total_return', 'max_drawdown_pct']

const METRIC_LABELS: Record<string, string> = {
  sharpe_ratio:     'Sharpe',
  cagr:             'CAGR',
  win_rate:         'Win Rate',
  profit_factor:    'PF',
  total_return:     'Return',
  max_drawdown_pct: 'Max DD',
}

export function Strategies() {
  const [results, setResults] = useState<StrategyResult[]>([])
  const [metric, setMetric]   = useState('sharpe_ratio')
  const [decision, setDec]    = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    strategiesApi.list(metric, 100)
      .then(r => setResults(decision ? r.filter(x => x.gate_decision.toUpperCase() === decision.toUpperCase()) : r))
      .finally(() => setLoading(false))
  }, [metric, decision])

  return (
    <div className="flex flex-col h-full">
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Strategy Results</span>
          <span className="ml-3 text-[10px] text-muted">All backtested strategies ranked by performance</span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <label className="field-label">Sort</label>
            <select value={metric} onChange={e => setMetric(e.target.value)} className="field-select text-[10px]">
              {METRICS.map(m => <option key={m} value={m}>{METRIC_LABELS[m] ?? m}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-1.5">
            <label className="field-label">Gate</label>
            <select value={decision} onChange={e => setDec(e.target.value)} className="field-select text-[10px]">
              <option value="">All</option>
              <option value="PROMISING">Promising</option>
              <option value="NEEDS IMPROVEMENT">Needs Imp.</option>
              <option value="REJECT">Rejected</option>
            </select>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <div className="p-5"><LoadingState /></div>}
        {!loading && results.length === 0 && (
          <div className="p-5">
            <EmptyState
              message="No results found."
              action={<Link to="/research" className="text-accent text-xs hover:underline">Run research first →</Link>}
            />
          </div>
        )}
        {!loading && results.length > 0 && (
          <>
            <table className="w-full table-dense">
              <thead>
                <tr className="border-b border-border bg-surface sticky top-0">
                  <th>Strategy</th>
                  <th>Market</th>
                  <th className="text-right">Sharpe</th>
                  <th className="text-right">CAGR</th>
                  <th className="text-right">Max DD</th>
                  <th className="text-right">Win Rate</th>
                  <th className="text-right">PF</th>
                  <th className="text-right">Trades</th>
                  <th>Gate</th>
                  <th className="max-w-[120px]">Params</th>
                </tr>
              </thead>
              <tbody>
                {results.map(r => (
                  <tr key={r.id}>
                    <td className="font-semibold">{r.strategy_class}</td>
                    <td className="font-mono text-muted">{r.symbol} {r.interval}</td>
                    <td className="text-right font-mono">{fmt(r.sharpe_ratio, 3)}</td>
                    <td className="text-right font-mono">{fmt(r.cagr, 4, true)}</td>
                    <td className="text-right font-mono text-red">{fmt(r.max_drawdown_pct, 2, true)}</td>
                    <td className="text-right font-mono">{fmt(r.win_rate, 2, true)}</td>
                    <td className="text-right font-mono">{fmt(r.profit_factor, 3)}</td>
                    <td className="text-right font-mono">{r.total_trades}</td>
                    <td><StatusBadge status={r.gate_decision} /></td>
                    <td className="font-mono text-muted text-[10px] max-w-[120px] truncate" title={r.params}>{r.params?.slice(0, 40)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-3 py-1.5 text-[9px] text-muted border-t border-border">{results.length} result(s)</div>
          </>
        )}
      </div>
    </div>
  )
}
