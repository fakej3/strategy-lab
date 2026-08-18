import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { CandlestickChart, FlaskConical, TrendingUp, ChevronUp, ChevronDown } from 'lucide-react'
import { strategiesApi } from '../api/strategies'
import { cn } from '../lib/cn'
import { fmt } from '../lib/format'
import type { StrategyResult } from '../types'

type SortKey = 'sharpe_ratio' | 'cagr' | 'max_drawdown_pct' | 'win_rate' | 'profit_factor' | 'total_trades'
type SortDir = 'asc' | 'desc'
type Filter  = '' | 'PROMISING' | 'NEEDS IMPROVEMENT' | 'REJECT'

function gateStyle(g: string): { dot: string; label: string; text: string } {
  const u = g.toUpperCase()
  if (u === 'PROMISING')        return { dot: 'bg-green',  label: 'PASS', text: 'text-green' }
  if (u.includes('IMPROVEMENT')) return { dot: 'bg-amber',  label: 'WORK', text: 'text-amber' }
  return                               { dot: 'bg-muted2', label: 'FAIL', text: 'text-muted2' }
}

function sharpeColor(v: number | null): string {
  if (v == null) return 'text-muted2'
  if (v >= 1.5)  return 'text-green'
  if (v >= 0.8)  return 'text-amber'
  return 'text-red'
}

export function Strategies() {
  const navigate  = useNavigate()
  const [results, setResults]   = useState<StrategyResult[]>([])
  const [loading, setLoading]   = useState(true)
  const [filter,  setFilter]    = useState<Filter>('')
  const [sortKey, setSortKey]   = useState<SortKey>('sharpe_ratio')
  const [sortDir, setSortDir]   = useState<SortDir>('desc')

  useEffect(() => {
    strategiesApi.list('sharpe_ratio', 200)
      .then(r => setResults(r))
      .finally(() => setLoading(false))
  }, [])

  function sort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const filtered = results.filter(r => !filter || r.gate_decision.toUpperCase() === filter || (filter === 'NEEDS IMPROVEMENT' && r.gate_decision.toUpperCase().includes('IMPROVEMENT')))

  const sorted = [...filtered].sort((a, b) => {
    const av = (a as unknown as Record<string, unknown>)[sortKey] as number | null ?? -Infinity
    const bv = (b as unknown as Record<string, unknown>)[sortKey] as number | null ?? -Infinity
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  const counts = {
    all:      results.length,
    pass:     results.filter(r => r.gate_decision.toUpperCase() === 'PROMISING').length,
    work:     results.filter(r => r.gate_decision.toUpperCase().includes('IMPROVEMENT')).length,
    fail:     results.filter(r => r.gate_decision.toUpperCase() === 'REJECT').length,
  }

  const best = results.filter(r => r.gate_decision.toUpperCase() === 'PROMISING')
    .sort((a, b) => (b.sharpe_ratio ?? 0) - (a.sharpe_ratio ?? 0))[0]

  function deploy(r: StrategyResult) {
    const p = new URLSearchParams({ symbol: r.symbol, interval: r.interval, strategy: r.strategy_class })
    navigate(`/paper-trading?${p}`)
  }

  if (loading) return (
    <div className="flex h-full items-center justify-center bg-bg">
      <div className="flex items-center gap-2 text-muted text-sm">
        <span className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin" />
        Loading…
      </div>
    </div>
  )

  if (results.length === 0) return (
    <div className="flex flex-col h-full bg-bg">
      <div className="shrink-0 flex items-center gap-3 px-5 h-10 border-b border-border bg-surface">
        <span className="text-sm font-semibold text-text">Strategies</span>
      </div>
      <div className="flex-1 overflow-auto scrollbar-thin">
        <div className="p-6 max-w-4xl">
          <div className="flex items-start gap-6">
            {/* Left: intro */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-9 h-9 rounded-lg bg-s3 border border-border flex items-center justify-center">
                  <FlaskConical size={16} className="text-muted2" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-text">No results yet</div>
                  <div className="text-xs text-muted">Run a research job to generate backtest results</div>
                </div>
              </div>
              <p className="text-sm text-muted mb-5 leading-relaxed">
                Backtest <strong className="text-text">EMACrossover</strong> across 20 parameter combinations.
                Results will appear here ranked by Sharpe ratio, with gate decisions for each configuration.
              </p>
              <Link
                to="/research"
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-accent text-bg text-sm font-bold rounded-lg hover:bg-amber-400 transition-colors"
              >
                <FlaskConical size={14} />
                Run First Research
              </Link>
            </div>

            {/* Right: strategy preview */}
            <div className="w-[280px] shrink-0 border border-border rounded-xl bg-surface p-5">
              <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-3">AVAILABLE STRATEGY</div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <div className="text-sm font-semibold text-text">EMACrossover</div>
                  <div className="text-xs text-muted font-mono">2 params · 20 configurations</div>
                </div>
                <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center">
                  <TrendingUp size={14} className="text-accent" />
                </div>
              </div>
              <div className="flex flex-col gap-2 text-xs">
                {[
                  { l: 'Fast EMA', v: '5, 10, 15, 20' },
                  { l: 'Slow EMA', v: '30, 40, 50, 100, 200' },
                ].map(({ l, v }) => (
                  <div key={l} className="bg-s3 rounded-lg px-3 py-2.5">
                    <div className="text-[10px] text-muted2 mb-1">{l}</div>
                    <div className="font-mono text-text text-[11px]">{v}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4 pt-4 border-t border-border">
                <div className="text-[10px] text-muted2 mb-2">GATE THRESHOLDS</div>
                <div className="flex flex-col gap-1 text-[11px] font-mono">
                  <div className="flex justify-between"><span className="text-green">PASS</span><span className="text-muted">Sharpe ≥ 1.5</span></div>
                  <div className="flex justify-between"><span className="text-amber">WORK</span><span className="text-muted">Sharpe ≥ 0.8</span></div>
                  <div className="flex justify-between"><span className="text-muted2">FAIL</span><span className="text-muted">Sharpe &lt; 0.8</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Header */}
      <div className="shrink-0 flex items-center justify-between px-5 h-10 border-b border-border bg-surface">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-text">Strategies</span>
          <span className="text-xs font-mono text-muted2">{results.length} results</span>
        </div>
        {best && (
          <button
            onClick={() => deploy(best)}
            className="flex items-center gap-1.5 px-3 h-7 bg-green/10 border border-green/20 text-green text-xs font-bold rounded hover:bg-green/15 transition-colors"
          >
            <CandlestickChart size={11} />
            Deploy Best
          </button>
        )}
      </div>

      {/* Filter + sort tabs */}
      <div className="shrink-0 flex items-center justify-between px-5 py-2 border-b border-border bg-surface">
        <div className="flex items-center gap-0.5">
          {([
            { v: '',                   l: 'All',      c: counts.all,  dot: '' },
            { v: 'PROMISING',          l: 'Passing',  c: counts.pass, dot: 'bg-green' },
            { v: 'NEEDS IMPROVEMENT',  l: 'Needs Work', c: counts.work, dot: 'bg-amber' },
            { v: 'REJECT',             l: 'Rejected', c: counts.fail, dot: 'bg-muted2' },
          ] as { v: Filter; l: string; c: number; dot: string }[]).map(({ v, l, c, dot }) => (
            <button
              key={v}
              onClick={() => setFilter(v)}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors',
                filter === v ? 'bg-s3 text-text' : 'text-muted hover:text-text hover:bg-s2',
              )}
            >
              {dot && <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot)} />}
              {l}
              {c > 0 && <span className="text-[10px] font-mono text-muted2">{c}</span>}
            </button>
          ))}
        </div>
        <div className="text-[10px] text-muted2 font-mono">{sorted.length} shown</div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto scrollbar-thin">
        <table className="w-full text-xs font-mono">
          <thead className="sticky top-0 bg-surface z-10">
            <tr className="border-b border-border">
              <th className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-5 py-2.5">Strategy</th>
              <th className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-3 py-2.5">Symbol</th>
              <th className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-3 py-2.5">TF</th>
              <th className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-3 py-2.5">Params</th>
              {(['sharpe_ratio','cagr','max_drawdown_pct','win_rate','profit_factor','total_trades'] as SortKey[]).map(k => (
                <SortTh key={k} k={k} current={sortKey} dir={sortDir} onSort={sort} />
              ))}
              <th className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-3 py-2.5">Gate</th>
              <th className="px-3 py-2.5 w-20" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const gate = gateStyle(r.gate_decision)
              let params = '—'
              try { const p = JSON.parse(r.params); params = Object.entries(p).map(([k,v]) => `${k}=${v}`).join(', ') } catch {}

              return (
                <tr key={r.id} className="border-b border-border/30 hover:bg-s2/50 transition-colors group">
                  <td className="px-5 py-2 text-text font-semibold">{r.strategy_class}</td>
                  <td className="px-3 py-2 text-muted">{r.symbol}</td>
                  <td className="px-3 py-2 text-muted">{r.interval}</td>
                  <td className="px-3 py-2 text-muted2 max-w-[160px] truncate text-[10px]" title={params}>{params}</td>
                  <td className="px-3 py-2">
                    <span className={cn('font-semibold', sharpeColor(r.sharpe_ratio))}>{fmt(r.sharpe_ratio, 2)}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={r.cagr != null && r.cagr > 0 ? 'text-green' : 'text-red'}>
                      {r.cagr != null ? `${r.cagr > 0 ? '+' : ''}${(r.cagr * 100).toFixed(1)}%` : '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-red">
                    {r.max_drawdown_pct != null ? `${(r.max_drawdown_pct * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td className="px-3 py-2 text-muted">{fmt(r.profit_factor, 2)}</td>
                  <td className="px-3 py-2 text-muted">{r.total_trades}</td>
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-1.5">
                      <span className={cn('w-1.5 h-1.5 rounded-full', gate.dot)} />
                      <span className={cn('text-[10px] font-bold', gate.text)}>{gate.label}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {r.gate_decision.toUpperCase() !== 'REJECT' && (
                      <button
                        onClick={() => deploy(r)}
                        className="opacity-0 group-hover:opacity-100 flex items-center gap-1 px-2 py-1 bg-green/10 border border-green/20 text-green text-[10px] font-bold rounded hover:bg-green/20 transition-all"
                      >
                        <CandlestickChart size={10} />
                        Deploy
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SortTh({ k, current, dir, onSort }: { k: SortKey; current: SortKey; dir: SortDir; onSort: (k: SortKey) => void }) {
  const labels: Record<SortKey, string> = {
    sharpe_ratio: 'Sharpe', cagr: 'CAGR', max_drawdown_pct: 'DD',
    win_rate: 'Win%', profit_factor: 'PF', total_trades: 'Trades',
  }
  const active = k === current
  return (
    <th
      className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-3 py-2.5 cursor-pointer hover:text-text transition-colors select-none"
      onClick={() => onSort(k)}
    >
      <span className="flex items-center gap-1">
        {labels[k]}
        {active ? (dir === 'desc' ? <ChevronDown size={9} className="text-accent" /> : <ChevronUp size={9} className="text-accent" />) : null}
      </span>
    </th>
  )
}
