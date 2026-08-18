import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  FlaskConical, BarChart2, CandlestickChart,
  ArrowRight, Activity, Zap,
} from 'lucide-react'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { botApi } from '../api/bot'
import { StatusBadge } from '../components/ui/Badge'
import { fmtTime, fmtElapsed, fmt, fmtSign } from '../lib/format'
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

  const running     = jobs.filter(j => j.status === 'running')
  const recent      = jobs.slice(0, 8)
  const activeCount = running.length + (bot?.running ? 1 : 0)

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
        {loading ? (
          <div className="flex items-center justify-center gap-3 py-24 text-muted">
            <span className="w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin" />
            <span className="text-sm">Loading…</span>
          </div>
        ) : (
          <div className="p-6 flex flex-col gap-6 max-w-5xl">

            {/* Section A — System status bar */}
            {(running.length > 0 || bot?.running) && (
              <SystemStatusBar running={running} bot={bot} />
            )}

            {/* Section B — Stats tiles */}
            {stats && (
              <div className="grid grid-cols-4 gap-3">
                <StatTile
                  label="Total Strategies"
                  value={stats.total ?? 0}
                  sub="backtested results"
                />
                <StatTile
                  label="Best Sharpe"
                  value={stats.best_sharpe != null ? fmt(stats.best_sharpe, 2) : '—'}
                  colorClass="text-accent"
                  sub="top performer"
                />
                <StatTile
                  label="Gate Passed"
                  value={(stats.promising ?? 0) + (stats.needs_imp ?? 0)}
                  colorClass="text-green"
                  sub="promising + needs work"
                />
                <StatTile
                  label="Active"
                  value={activeCount}
                  colorClass={activeCount > 0 ? 'text-green' : undefined}
                  sub={activeCount > 0 ? `running now` : 'none running'}
                  pulse={activeCount > 0}
                />
              </div>
            )}

            {/* Section C — Bot status card */}
            {bot?.running && <BotCard bot={bot} />}

            {/* Section D — Recent research */}
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
                      <span className="font-mono text-xs text-muted shrink-0">
                        {j.job_id.slice(0, 12)}…
                      </span>
                      <span className="text-xs text-muted flex-1 min-w-0 truncate">
                        {fmtTime(j.started_at)}
                      </span>
                      {j.n_tested != null && (
                        <span className="text-xs font-mono shrink-0">
                          <span className="text-green font-semibold">{j.n_passed ?? 0}</span>
                          <span className="text-muted2"> / {j.n_tested}</span>
                        </span>
                      )}
                      {j.elapsed_secs != null && (
                        <span className="text-xs text-muted font-mono shrink-0">
                          {fmtElapsed(j.elapsed_secs)}
                        </span>
                      )}
                      <ArrowRight
                        size={13}
                        className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                      />
                    </Link>
                  ))}
                </div>
              )}
            </div>

            {/* Section E — Quick actions */}
            {stats != null && (stats.total ?? 0) > 0 && (
              <div className="grid grid-cols-2 gap-3">
                <QuickTile
                  to="/strategies"
                  icon={<BarChart2 size={20} className="text-accent" />}
                  label="Strategy Results"
                  sub={`${stats.total ?? 0} backtested · ${(stats.promising ?? 0) + (stats.needs_imp ?? 0)} passed gate`}
                />
                <QuickTile
                  to="/paper-trading"
                  icon={<CandlestickChart size={20} className={bot?.running ? 'text-green' : 'text-muted'} />}
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

// ── Sub-components ─────────────────────────────────────────────────────────────

function SystemStatusBar({ running, bot }: { running: Job[]; bot: BotStatus | null }) {
  return (
    <div className="flex items-center gap-6 px-4 py-2.5 bg-surface border border-border rounded-xl">
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
        <span className="text-[10px] font-semibold tracking-widest text-muted2 uppercase">Live</span>
      </div>

      <div className="flex items-center gap-6 flex-1 min-w-0">
        {running.length > 0 && (
          <span className="flex items-center gap-1.5 text-xs text-amber">
            <Activity size={12} className="shrink-0" />
            {running.length} research job{running.length > 1 ? 's' : ''} running
          </span>
        )}
        {bot?.running && (
          <span className="flex items-center gap-1.5 text-xs text-green">
            <Zap size={12} className="shrink-0" />
            Paper trading · {bot.strategy}
          </span>
        )}
      </div>

      {running.length > 0 && (
        <Link
          to="/jobs"
          className="shrink-0 text-xs font-semibold text-accent flex items-center gap-1 hover:opacity-80"
        >
          View jobs <ArrowRight size={11} />
        </Link>
      )}
    </div>
  )
}

function StatTile({
  label, value, sub, colorClass, pulse,
}: {
  label: string
  value: string | number
  sub?: string
  colorClass?: string
  pulse?: boolean
}) {
  return (
    <div className="bg-surface border border-border rounded-xl px-5 py-5">
      <div className="text-xs text-muted mb-2">{label}</div>
      <div className={cn(
        'text-3xl font-bold font-mono tabular-nums leading-none flex items-center gap-2',
        colorClass ?? 'text-text',
      )}>
        {value}
        {pulse && (
          <span className="inline-block w-2 h-2 rounded-full bg-green animate-pulse" />
        )}
      </div>
      {sub && <div className="text-xs text-muted2 mt-1.5">{sub}</div>}
    </div>
  )
}

function BotCard({ bot }: { bot: BotStatus }) {
  const upnl = bot.unrealized_pnl
  const rpnl = bot.realized_pnl

  return (
    <div className="bg-surface border border-green/20 rounded-xl p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-3 flex-1 min-w-0">
          {/* Strategy + symbols */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="w-2 h-2 rounded-full bg-green animate-pulse shrink-0" />
            <span className="text-sm font-semibold text-text">{bot.strategy}</span>
            {bot.symbols?.length > 0 && (
              <span className="text-xs text-muted px-2 py-0.5 bg-s3 border border-border rounded-full font-mono">
                {bot.symbols.join(' · ')}
              </span>
            )}
          </div>

          {/* Metrics */}
          <div className="flex items-center gap-6 flex-wrap">
            <BotMetric label="Capital"        value={`$${fmt(bot.capital, 0)}`} />
            <BotMetric label="Equity"         value={`$${fmt(bot.equity, 0)}`} />
            <BotMetric
              label="Unrealized PnL"
              value={fmtSign(upnl)}
              colorClass={upnl > 0 ? 'text-green' : upnl < 0 ? 'text-red' : 'text-muted'}
            />
            <BotMetric
              label="Realized PnL"
              value={fmtSign(rpnl)}
              colorClass={rpnl > 0 ? 'text-green' : rpnl < 0 ? 'text-red' : 'text-muted'}
            />
            {(bot.open_positions?.length ?? 0) > 0 && (
              <BotMetric label="Positions" value={String(bot.open_positions.length)} />
            )}
          </div>
        </div>

        {/* CTA */}
        <Link
          to="/paper-trading"
          className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-green border border-green/25 rounded-lg hover:bg-green/10 transition-colors"
        >
          View Terminal <ArrowRight size={12} />
        </Link>
      </div>
    </div>
  )
}

function BotMetric({
  label, value, colorClass,
}: {
  label: string
  value: string
  colorClass?: string
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold tracking-widest text-muted2 uppercase mb-0.5">{label}</div>
      <div className={cn('text-sm font-mono font-semibold', colorClass ?? 'text-text')}>{value}</div>
    </div>
  )
}

function QuickTile({
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
        'flex items-center gap-4 px-5 py-5 bg-surface border rounded-xl hover:bg-s2 transition-colors group',
        active ? 'border-green/20' : 'border-border hover:border-border2',
      )}
    >
      <div className={cn(
        'w-11 h-11 rounded-xl flex items-center justify-center shrink-0',
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

