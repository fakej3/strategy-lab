import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { strategiesApi } from '../api/strategies'
import { StatusBadge } from '../components/ui/Badge'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmt } from '../lib/format'
import type { StrategyResult } from '../types'

const METRICS = ['sharpe_ratio', 'cagr', 'win_rate', 'profit_factor', 'total_return', 'max_drawdown_pct']

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
    <div className="p-6 max-w-5xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Strategy Results</h1>
      <p className="text-[12px] text-muted mb-5">All backtested strategies ranked by performance</p>

      <div className="flex gap-3 mb-4 flex-wrap items-end">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Sort By</label>
          <select value={metric} onChange={e => setMetric(e.target.value)}
            className="bg-s2 border border-border rounded px-2.5 py-1.5 text-[11px] text-text focus:outline-none focus:border-accent">
            {METRICS.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Gate Decision</label>
          <select value={decision} onChange={e => setDec(e.target.value)}
            className="bg-s2 border border-border rounded px-2.5 py-1.5 text-[11px] text-text focus:outline-none focus:border-accent">
            <option value="">All</option>
            <option value="PROMISING">Promising</option>
            <option value="NEEDS IMPROVEMENT">Needs Improvement</option>
            <option value="REJECT">Rejected</option>
          </select>
        </div>
      </div>

      {loading && <LoadingState />}
      {!loading && results.length === 0 && (
        <EmptyState message="No results found." action={<Link to="/research" className="text-accent text-sm hover:underline">Run research first →</Link>} />
      )}
      {!loading && results.length > 0 && (
        <>
          <div className="bg-surface border border-border rounded-md overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  {['Strategy', 'Params', 'Market', 'Sharpe', 'CAGR', 'Max DD', 'Win Rate', 'PF', 'Trades', 'Gate'].map(h => (
                    <th key={h} className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map(r => (
                  <tr key={r.id} className="border-b border-border last:border-0 hover:bg-s2">
                    <td className="px-3 py-2 font-semibold whitespace-nowrap">{r.strategy_class}</td>
                    <td className="px-3 py-2 font-mono text-muted max-w-[120px] truncate" title={r.params}>{r.params?.slice(0, 50)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{r.symbol} {r.interval}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmt(r.sharpe_ratio, 3)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmt(r.cagr, 4, true)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmt(r.max_drawdown_pct, 2, true)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmt(r.win_rate, 2, true)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmt(r.profit_factor, 3)}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.total_trades}</td>
                    <td className="px-3 py-2"><StatusBadge status={r.gate_decision} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-muted mt-2">{results.length} result(s)</p>
        </>
      )}
    </div>
  )
}
