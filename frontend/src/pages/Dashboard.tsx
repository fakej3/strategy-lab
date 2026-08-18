import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical, TrendingUp, BarChart2, CandlestickChart, ArrowRight, CheckCircle2 } from 'lucide-react'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { botApi } from '../api/bot'
import { StatusBadge } from '../components/ui/Badge'
import { fmtTime, fmtElapsed, fmt } from '../lib/format'
import { cn } from '../lib/cn'
import type { Stats, Job, BotStatus } from '../types'

export function Dashboard() {
  const [stats,   setStats]   = useState<Stats | null>(null)
  const [jobs,    setJobs]    = useState<Job[]>([])
  const [bot,     setBot]     = useState<BotStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      statsApi.get(),
      jobsApi.list(),
      botApi.status().catch(() => null),
    ]).then(([s, j, b]) => {
      setStats(s)
      setJobs(j)
      setBot(b)
    }).finally(() => setLoading(false))
  }, [])

  const running = jobs.filter(j => j.status === 'running')
  const recent  = jobs.slice(0, 8)

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Home</span>
        <Link
          to="/research"
          className="inline-flex items-center gap-2 px-4 py-1.5 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors"
        >
          <FlaskConical size={14} />
          New Research Run
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* Active-work strip */}
        {!loading && (running.length > 0 || bot?.running) && (
          <div className="flex items-center gap-3 px-6 py-2.5 border-b border-amber/15 bg-amber/5">
            <span className="w-2 h-2 rounded-full bg-amber animate-pulse shrink-0" />
            <div className="flex items-center gap-5 text-sm">
              {running.length > 0 && (
                <span className="text-amber">
                  {running.length} research job{running.length > 1 ? 's' : ''} running
                </span>
              )}
              {bot?.running && (
                <span className="text-amber">
                  Paper trading · {bot.strategy}
                </span>
              )}
            </div>
            {running.length > 0 && (
              <Link to="/jobs" className="ml-auto text-xs font-semibold text-amber flex items-center gap-1 hover:opacity-80">
                View jobs <ArrowRight size={12} />
              </Link>
            )}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center gap-3 py-24 text-muted">
            <span className="w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin" />
            <span className="text-sm">Loading…</span>
          </div>
        ) : (
          <div className="p-6 flex flex-col gap-6 max-w-5xl">
            {/* Stats tiles */}
            {stats && (
              <div className="grid grid-cols-4 gap-3">
                <StatTile
                  label="Total Results"
                  value={stats.total ?? 0}
                  icon={<BarChart2 size={15} />}
                  sub="backtested strategies"
                />
                <StatTile
                  label="Best Sharpe"
                  value={stats.best_sharpe != null ? fmt(stats.best_sharpe, 2) : '—'}
                  icon={<TrendingUp size={15} />}
                  accent
                  sub="top performer"
                />
                <StatTile
                  label="Passed Gate"
                  value={(stats.promising ?? 0) + (stats.needs_imp ?? 0)}
                  positive
                  sub="promising + needs work"
                />
                <StatTile
                  label="Running"
                  value={running.length}
                  pulse={running.length > 0}
                  sub={running.length > 0 ? 'active right now' : 'no active jobs'}
                />
              </div>
            )}

            {/* Recent research jobs */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-text">Recent Research</h2>
                {recent.length > 0 && (
                  <Link to="/jobs" className="text-xs text-accent hover:opacity-80 flex items-center gap-1">
                    All runs <ArrowRight size={11} />
                  </Link>
                )}
              </div>

              {recent.length === 0 ? (
                <div className="flex flex-col items-center gap-4 py-20 bg-surface border border-dashed border-border rounded-xl">
                  <div className="w-14 h-14 rounded-full bg-s2 border border-border flex items-center justify-center">
                    <FlaskConical size={24} className="text-muted2" />
                  </div>
                  <div className="text-center">
                    <p className="text-base font-semibold text-text">No research runs yet</p>
                    <p className="text-sm text-muted mt-1">Configure and launch a backtest to see results here.</p>
                  </div>
                  <Link
                    to="/research"
                    className="inline-flex items-center gap-2 px-5 py-2 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors"
                  >
                    <FlaskConical size={14} />
                    Start Research
                  </Link>
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {recent.map(j => (
                    <Link
                      key={j.job_id}
                      to={`/jobs/${j.job_id}`}
                      className="flex items-center gap-4 px-4 py-3 bg-surface border border-border rounded-lg hover:border-border2 hover:bg-s2 transition-colors group"
                    >
                      <StatusBadge status={j.status} />
                      <span className="font-mono text-xs text-muted shrink-0">{j.job_id.slice(0, 14)}…</span>
                      <span className="text-sm text-muted flex-1 min-w-0 truncate">{fmtTime(j.started_at)}</span>
                      {j.n_tested != null && (
                        <span className="text-xs font-mono shrink-0">
                          <span className="text-green font-semibold">{j.n_passed ?? 0}</span>
                          <span className="text-muted2"> / {j.n_tested} passed</span>
                        </span>
                      )}
                      {j.elapsed_secs != null && (
                        <span className="text-xs text-muted font-mono shrink-0">{fmtElapsed(j.elapsed_secs)}</span>
                      )}
                      <ArrowRight size={14} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                    </Link>
                  ))}
                </div>
              )}
            </div>

            {/* Quick navigation tiles */}
            {stats != null && (stats.total ?? 0) > 0 && (
              <div className="grid grid-cols-2 gap-3">
                <QuickLink
                  to="/strategies"
                  icon={<BarChart2 size={17} className="text-accent" />}
                  label="Strategy Results"
                  sub={`${stats.total ?? 0} backtested · ${(stats.promising ?? 0) + (stats.needs_imp ?? 0)} passed`}
                />
                <QuickLink
                  to="/paper-trading"
                  icon={<CandlestickChart size={17} className={bot?.running ? 'text-green' : 'text-muted'} />}
                  label="Paper Trading"
                  sub={bot?.running ? `Running · ${bot.strategy}` : 'Configure and launch'}
                  active={bot?.running}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function StatTile({
  label, value, sub, icon, accent, positive, negative, pulse,
}: {
  label: string
  value: string | number
  sub?: string
  icon?: React.ReactNode
  accent?: boolean
  positive?: boolean
  negative?: boolean
  pulse?: boolean
}) {
  return (
    <div className="bg-surface border border-border rounded-xl px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-muted">{label}</span>
        <span className="text-muted opacity-50">{icon}</span>
      </div>
      <div className={cn(
        'text-4xl font-bold font-mono tabular-nums leading-none',
        accent   && 'text-accent',
        positive && 'text-green',
        negative && 'text-red',
        !accent && !positive && !negative && 'text-text',
      )}>
        {value}
        {pulse && (
          <span className="ml-2 inline-block w-2 h-2 rounded-full bg-green animate-pulse align-middle" />
        )}
      </div>
      {sub && <div className="text-xs text-muted2 mt-2">{sub}</div>}
    </div>
  )
}

function QuickLink({
  to, icon, label, sub, active,
}: {
  to: string
  icon: React.ReactNode
  label: string
  sub: string
  active?: boolean
}) {
  return (
    <Link
      to={to}
      className={cn(
        'flex items-center gap-4 px-4 py-4 bg-surface border rounded-xl hover:bg-s2 transition-colors group',
        active ? 'border-green/20' : 'border-border hover:border-border2',
      )}
    >
      <div className={cn(
        'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
        active ? 'bg-green/10' : 'bg-s3',
      )}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-text">{label}</div>
        <div className={cn('text-xs mt-0.5', active ? 'text-green' : 'text-muted')}>{sub}</div>
      </div>
      <ArrowRight size={15} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
    </Link>
  )
}

// Prevent unused import warning
void CheckCircle2
