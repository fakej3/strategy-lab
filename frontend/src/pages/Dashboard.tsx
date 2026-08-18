import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  FlaskConical, BarChart2, CandlestickChart, ArrowRight,
  CheckCircle2, XCircle, AlertCircle, Clock, Activity,
  ChevronRight, Zap,
} from 'lucide-react'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { botApi } from '../api/bot'
import { logsApi } from '../api/logs'
import { strategiesApi } from '../api/strategies'
import { fmt, fmtElapsed, pnlClass } from '../lib/format'
import { cn } from '../lib/cn'
import type { Stats, Job, BotStatus, StrategyResult } from '../types'

interface ActivityItem { ts: string; text: string; type: 'ok' | 'error' | 'warn' | 'info' }

function parseActivity(lines: string[]): ActivityItem[] {
  const items: ActivityItem[] = []
  for (let i = lines.length - 1; i >= 0 && items.length < 20; i--) {
    const line = lines[i]
    if (!line.trim()) continue
    const tsMatch = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/)
    const ts = tsMatch ? tsMatch[1].slice(11) : ''
    const text = line.replace(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+\s*/, '').trim()
    if (!text || /^[—\-─]+$/.test(text)) continue
    let type: ActivityItem['type'] = 'info'
    if (/✓|complete|passed|success/i.test(text) && !/fail/i.test(text)) type = 'ok'
    else if (/✗|✘|error|fail|blocked|exception/i.test(text)) type = 'error'
    else if (/⚠|warn/i.test(text)) type = 'warn'
    items.unshift({ ts, text: text.slice(0, 100), type })
  }
  return items
}

export function Dashboard() {
  const navigate = useNavigate()
  const [stats,      setStats]      = useState<Stats | null>(null)
  const [jobs,       setJobs]       = useState<Job[]>([])
  const [bot,        setBot]        = useState<BotStatus | null>(null)
  const [results,    setResults]    = useState<StrategyResult[]>([])
  const [activity,   setActivity]   = useState<ActivityItem[]>([])
  const [loading,    setLoading]    = useState(true)

  useEffect(() => {
    Promise.all([
      statsApi.get().catch(() => null),
      jobsApi.list().catch(() => []),
      botApi.status().catch(() => null),
      strategiesApi.list('sharpe_ratio', 20).catch(() => []),
      logsApi.get(200).catch(() => ({ lines: [] })),
    ]).then(([s, j, b, r, logs]) => {
      setStats(s)
      setJobs(j as Job[])
      setBot(b)
      setResults(r as StrategyResult[])
      setActivity(parseActivity((logs as { lines: string[] }).lines))
    }).finally(() => setLoading(false))
  }, [])

  const running = jobs.filter(j => j.status === 'running')
  const recent  = jobs.filter(j => j.status !== 'running').slice(0, 8)
  const hasData = (stats?.total ?? 0) > 0 || jobs.length > 0

  if (loading) return (
    <div className="flex h-full items-center justify-center bg-bg">
      <div className="flex items-center gap-2 text-muted text-sm">
        <span className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin" />
        Loading…
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full bg-bg overflow-hidden">
      {/* Top bar */}
      <div className="shrink-0 flex items-center gap-0 h-10 border-b border-border bg-surface px-4">
        <span className="text-xs font-semibold text-text mr-4">EdgeLab</span>
        <StatusPip color={bot?.running ? 'green' : 'muted'} label="BOT" value={bot?.running ? `${bot.strategy}` : 'STOPPED'} />
        <Sep />
        <StatusPip color={running.length > 0 ? 'amber' : 'muted'} label="RESEARCH" value={running.length > 0 ? `${running.length} RUNNING` : 'IDLE'} />
        <Sep />
        <StatusPip color={(stats?.total ?? 0) > 0 ? 'green' : 'muted'} label="STRATEGIES" value={`${stats?.total ?? 0} TESTED`} />
        <Sep />
        <StatusPip color={jobs.length > 0 ? 'accent' : 'muted'} label="JOBS" value={`${jobs.length} TOTAL`} />
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => navigate('/research')}
            className="flex items-center gap-1.5 px-3 h-7 bg-accent text-bg text-xs font-bold rounded hover:bg-amber-400 transition-colors"
          >
            <FlaskConical size={11} />
            NEW RESEARCH
          </button>
        </div>
      </div>

      {/* Main workspace */}
      <div className="flex-1 overflow-hidden flex">

        {/* Left: main content */}
        <div className="flex-1 overflow-y-auto scrollbar-thin">

          {/* Running jobs — always prominent when active */}
          {running.length > 0 && (
            <div className="border-b border-border/60 bg-amber/3">
              {running.map(j => <RunningBanner key={j.job_id} job={j} />)}
            </div>
          )}

          {/* Research results table */}
          <div className="border-b border-border/60">
            <SectionHeader label="RESEARCH RESULTS" count={results.length} to="/strategies" />
            {results.length === 0 ? (
              <EmptyResearch />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="border-b border-border/50">
                      {['Strategy','Symbol','TF','Sharpe','CAGR','DD','Win%','Trades','Gate'].map(h => (
                        <th key={h} className="text-left text-[10px] font-semibold tracking-widest text-muted2 px-4 py-2 first:pl-5">{h}</th>
                      ))}
                      <th className="px-4 py-2 w-8" />
                    </tr>
                  </thead>
                  <tbody>
                    {results.slice(0, 10).map(r => <ResultRow key={r.id} r={r} navigate={navigate} />)}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Recent job runs */}
          <div className="border-b border-border/60">
            <SectionHeader label="JOB HISTORY" count={recent.length} to="/jobs" />
            {recent.length === 0 ? (
              <div className="px-5 py-4 text-xs text-muted">No completed jobs yet. <Link to="/research" className="text-accent hover:underline">Start research →</Link></div>
            ) : (
              <div>
                {recent.map(j => <JobRow key={j.job_id} job={j} />)}
              </div>
            )}
          </div>

          {/* Bot widget */}
          {bot?.running && (
            <div className="border-b border-border/60">
              <SectionHeader label="PAPER BOT" to="/paper-trading" />
              <BotWidget bot={bot} />
            </div>
          )}

          {/* Quick nav when empty */}
          {!hasData && !bot?.running && (
            <div className="p-5">
              <div className="text-[10px] font-semibold tracking-widest text-muted2 mb-3">QUICK START</div>
              <div className="grid grid-cols-3 gap-2">
                <QuickNav to="/research" icon={<FlaskConical size={14} />} label="Run Research" sub="Backtest EMACrossover across symbols and timeframes" />
                <QuickNav to="/strategies" icon={<BarChart2 size={14} />} label="View Strategies" sub="Browse and compare tested configurations" />
                <QuickNav to="/paper-trading" icon={<CandlestickChart size={14} />} label="Paper Trade" sub="Deploy your strategy with simulated capital" />
              </div>
            </div>
          )}
        </div>

        {/* Right: activity sidebar */}
        <div className="w-[280px] shrink-0 border-l border-border flex flex-col overflow-hidden">
          {/* Bot mini-status */}
          {bot?.running && (
            <Link to="/paper-trading" className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border bg-green/5 hover:bg-green/8 transition-colors">
              <span className="w-1.5 h-1.5 rounded-full bg-green animate-pulse shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-green truncate">{bot.strategy}</div>
                <div className="text-[10px] text-green/70 font-mono">{bot.symbols?.join(' · ')}</div>
              </div>
              <div className="text-right shrink-0">
                <div className={cn('text-xs font-mono font-semibold', pnlClass(bot.unrealized_pnl ?? 0))}>
                  {(bot.unrealized_pnl ?? 0) >= 0 ? '+' : ''}${Math.abs(bot.unrealized_pnl ?? 0).toFixed(0)}
                </div>
                <div className="text-[10px] text-muted2 font-mono">unrealized</div>
              </div>
            </Link>
          )}

          {/* Top performers */}
          {results.length > 0 && (
            <div className="border-b border-border">
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-[10px] font-semibold tracking-widest text-muted2">TOP PERFORMER</span>
                <Link to="/strategies" className="text-[10px] text-accent hover:underline">all →</Link>
              </div>
              <div className="px-3 pb-3">
                <TopResult r={results[0]} />
              </div>
            </div>
          )}

          {/* Activity feed */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
            <div className="flex items-center gap-1.5">
              <Activity size={11} className="text-muted2" />
              <span className="text-[10px] font-semibold tracking-widest text-muted2">ACTIVITY</span>
            </div>
            <Link to="/logs" className="text-[10px] text-accent hover:underline">logs →</Link>
          </div>
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {activity.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-muted2">No recent activity</div>
            ) : (
              <div className="divide-y divide-border/30">
                {activity.map((item, i) => (
                  <div key={i} className="flex items-start gap-2 px-3 py-1.5">
                    <div className="shrink-0 mt-0.5">
                      {item.type === 'ok'    && <CheckCircle2 size={10} className="text-green" />}
                      {item.type === 'error' && <XCircle      size={10} className="text-red" />}
                      {item.type === 'warn'  && <AlertCircle  size={10} className="text-amber" />}
                      {item.type === 'info'  && <Clock        size={10} className="text-muted2" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={cn('text-[10px] leading-snug break-words',
                        item.type === 'ok' ? 'text-green/90' : item.type === 'error' ? 'text-red/90' : item.type === 'warn' ? 'text-amber/90' : 'text-muted'
                      )}>
                        {item.text}
                      </div>
                      {item.ts && <div className="text-[9px] text-muted2 font-mono mt-0.5">{item.ts}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Sep() {
  return <span className="text-border mx-3 text-xs">|</span>
}

function StatusPip({ color, label, value }: { color: string; label: string; value: string }) {
  const dot = color === 'green' ? 'bg-green' : color === 'amber' ? 'bg-amber animate-pulse' : color === 'accent' ? 'bg-accent' : 'bg-muted2'
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot)} />
      <span className="text-[10px] font-semibold text-muted2 tracking-widest">{label}</span>
      <span className="text-[10px] font-mono text-muted">{value}</span>
    </div>
  )
}

function SectionHeader({ label, count, to }: { label: string; count?: number; to: string }) {
  return (
    <div className="flex items-center justify-between px-5 py-2.5 border-b border-border/50">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold tracking-widest text-muted2">{label}</span>
        {count !== undefined && count > 0 && (
          <span className="text-[10px] font-mono text-muted2 bg-s3 px-1.5 py-0.5 rounded">{count}</span>
        )}
      </div>
      <Link to={to} className="text-[10px] text-accent hover:underline flex items-center gap-0.5">
        view all <ChevronRight size={9} />
      </Link>
    </div>
  )
}

function RunningBanner({ job }: { job: Job }) {
  return (
    <Link to={`/jobs/${job.job_id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-amber/5 transition-colors">
      <span className="w-2 h-2 rounded-full bg-amber animate-pulse shrink-0" />
      <span className="text-xs font-semibold text-amber font-mono">RUNNING</span>
      <span className="text-xs text-muted font-mono">{job.job_id.slice(0, 12)}…</span>
      {job.progress_pct != null && (
        <>
          <div className="flex-1 max-w-[200px] h-1 bg-s3 rounded-full overflow-hidden">
            <div className="h-full bg-amber/60 rounded-full" style={{ width: `${job.progress_pct}%` }} />
          </div>
          <span className="text-xs font-mono text-amber">{job.progress_pct.toFixed(0)}%</span>
        </>
      )}
      {job.current_stage && <span className="text-xs text-muted2 font-mono truncate max-w-[200px]">{job.current_stage}</span>}
      <ArrowRight size={12} className="text-muted shrink-0 ml-auto" />
    </Link>
  )
}

function ResultRow({ r, navigate }: { r: StrategyResult; navigate: ReturnType<typeof useNavigate> }) {
  const gate = r.gate_decision?.toUpperCase() ?? ''
  const gateColor = gate === 'PROMISING' ? 'text-green' : gate.includes('IMPROVEMENT') ? 'text-amber' : 'text-muted2'
  const gateDot   = gate === 'PROMISING' ? 'bg-green' : gate.includes('IMPROVEMENT') ? 'bg-amber' : 'bg-muted2'
  return (
    <tr
      onClick={() => navigate('/strategies')}
      className="border-b border-border/30 hover:bg-s2/60 cursor-pointer transition-colors"
    >
      <td className="px-4 py-2 pl-5 text-text font-semibold">{r.strategy_class}</td>
      <td className="px-4 py-2 text-muted">{r.symbol}</td>
      <td className="px-4 py-2 text-muted">{r.interval}</td>
      <td className="px-4 py-2">
        <span className={cn('font-semibold', (r.sharpe_ratio ?? 0) >= 1.5 ? 'text-green' : (r.sharpe_ratio ?? 0) >= 0.8 ? 'text-amber' : 'text-red')}>
          {fmt(r.sharpe_ratio, 2)}
        </span>
      </td>
      <td className="px-4 py-2">
        <span className={r.cagr != null && r.cagr > 0 ? 'text-green' : 'text-red'}>
          {r.cagr != null ? `${r.cagr > 0 ? '+' : ''}${(r.cagr * 100).toFixed(1)}%` : '—'}
        </span>
      </td>
      <td className="px-4 py-2 text-red">
        {r.max_drawdown_pct != null ? `${(r.max_drawdown_pct * 100).toFixed(1)}%` : '—'}
      </td>
      <td className="px-4 py-2 text-muted">
        {r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : '—'}
      </td>
      <td className="px-4 py-2 text-muted">{r.total_trades}</td>
      <td className="px-4 py-2">
        <span className="flex items-center gap-1.5">
          <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', gateDot)} />
          <span className={cn('text-[10px] font-semibold', gateColor)}>
            {gate === 'PROMISING' ? 'PASS' : gate.includes('IMPROVEMENT') ? 'WORK' : 'FAIL'}
          </span>
        </span>
      </td>
      <td className="px-4 py-2 w-8">
        <ArrowRight size={11} className="text-muted opacity-0 group-hover:opacity-100" />
      </td>
    </tr>
  )
}

function JobRow({ job }: { job: Job }) {
  const dot = job.status === 'done' ? 'bg-green' : job.status === 'failed' ? 'bg-red' : 'bg-muted2'
  const label = job.status === 'done' ? 'text-green' : job.status === 'failed' ? 'text-red' : 'text-muted2'
  return (
    <Link
      to={`/jobs/${job.job_id}`}
      className="flex items-center gap-3 px-5 py-2 hover:bg-s2/50 transition-colors border-b border-border/30"
    >
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot)} />
      <span className="font-mono text-[10px] text-muted2 shrink-0">{job.started_at?.slice(5,16).replace('T',' ') ?? '—'}</span>
      <span className={cn('text-[10px] font-semibold shrink-0', label)}>{job.status.toUpperCase()}</span>
      <span className="font-mono text-[10px] text-muted2 flex-1 truncate">{job.job_id.slice(0,12)}…</span>
      {job.n_tested != null && (
        <span className="font-mono text-[10px] shrink-0">
          <span className="text-green">{job.n_passed ?? 0}</span>
          <span className="text-muted2">/{job.n_tested} passed</span>
        </span>
      )}
      {job.elapsed_secs != null && (
        <span className="font-mono text-[10px] text-muted2 shrink-0">{fmtElapsed(job.elapsed_secs)}</span>
      )}
      <ArrowRight size={11} className="text-muted shrink-0" />
    </Link>
  )
}

function BotWidget({ bot }: { bot: BotStatus }) {
  const upnl = bot.unrealized_pnl ?? 0
  const rpnl = bot.realized_pnl ?? 0
  return (
    <div className="px-5 py-3">
      <div className="flex items-center gap-6 flex-wrap">
        {[
          { l: 'Capital',  v: `$${(bot.capital ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
          { l: 'Equity',   v: `$${(bot.equity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
          { l: 'Open P&L', v: `${upnl >= 0 ? '+' : ''}$${Math.abs(upnl).toFixed(2)}`, c: pnlClass(upnl) },
          { l: 'Realized', v: `${rpnl >= 0 ? '+' : ''}$${Math.abs(rpnl).toFixed(2)}`, c: pnlClass(rpnl) },
          { l: 'Positions', v: String(bot.open_positions?.length ?? 0) },
          { l: 'Strategy', v: bot.strategy },
        ].map(({ l, v, c }) => (
          <div key={l}>
            <div className="text-[9px] font-semibold tracking-widest text-muted2 mb-0.5">{l}</div>
            <div className={cn('text-sm font-mono font-semibold', c ?? 'text-text')}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function TopResult({ r }: { r: StrategyResult }) {
  return (
    <div className="bg-s2/60 rounded-lg p-2.5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-text">{r.strategy_class}</span>
        <span className="text-[10px] font-mono text-muted">{r.symbol} · {r.interval}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {[
          { l: 'Sharpe', v: fmt(r.sharpe_ratio, 2), c: (r.sharpe_ratio ?? 0) >= 1.5 ? 'text-green' : (r.sharpe_ratio ?? 0) >= 0.8 ? 'text-amber' : 'text-red' },
          { l: 'CAGR',   v: r.cagr != null ? `${r.cagr > 0 ? '+' : ''}${(r.cagr * 100).toFixed(1)}%` : '—', c: r.cagr != null && r.cagr > 0 ? 'text-green' : 'text-red' },
          { l: 'DD',     v: r.max_drawdown_pct != null ? `${(r.max_drawdown_pct * 100).toFixed(1)}%` : '—', c: 'text-red' },
          { l: 'Win%',   v: r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : '—', c: 'text-muted' },
        ].map(({ l, v, c }) => (
          <div key={l} className="flex items-center justify-between">
            <span className="text-[10px] text-muted2">{l}</span>
            <span className={cn('text-[11px] font-mono font-semibold', c)}>{v}</span>
          </div>
        ))}
      </div>
      <Link to="/paper-trading" className="mt-2.5 flex items-center justify-center gap-1.5 w-full py-1.5 bg-green/10 border border-green/20 text-green text-[10px] font-bold rounded hover:bg-green/15 transition-colors">
        <Zap size={10} />
        DEPLOY TO PAPER
      </Link>
    </div>
  )
}

function EmptyResearch() {
  return (
    <div className="flex items-center gap-4 px-5 py-5">
      <div className="w-8 h-8 rounded-lg bg-s3 flex items-center justify-center shrink-0">
        <FlaskConical size={14} className="text-muted2" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-text mb-0.5">No research results yet</div>
        <div className="text-xs text-muted">
          Run <strong className="text-accent">EMACrossover</strong> across BTCUSDT · 1H to test 20 parameter combinations.
        </div>
      </div>
      <Link
        to="/research"
        className="shrink-0 flex items-center gap-1.5 px-3 py-2 bg-accent text-bg text-xs font-bold rounded hover:bg-amber-400 transition-colors"
      >
        <FlaskConical size={12} />
        Run Research
      </Link>
    </div>
  )
}

function QuickNav({ to, icon, label, sub }: { to: string; icon: React.ReactNode; label: string; sub: string }) {
  return (
    <Link to={to} className="flex items-start gap-3 px-4 py-3.5 bg-surface border border-border rounded-xl hover:border-accent/40 hover:bg-s2 transition-colors group">
      <div className="w-7 h-7 rounded-lg bg-s3 flex items-center justify-center shrink-0 text-muted group-hover:text-accent transition-colors mt-0.5">
        {icon}
      </div>
      <div>
        <div className="text-sm font-semibold text-text mb-0.5">{label}</div>
        <div className="text-xs text-muted leading-snug">{sub}</div>
      </div>
    </Link>
  )
}
