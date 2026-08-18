import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  FlaskConical, BarChart2, CandlestickChart, ArrowRight,
  Activity, CheckCircle2, XCircle, AlertCircle, Clock,
  ChevronRight,
} from 'lucide-react'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { botApi } from '../api/bot'
import { logsApi } from '../api/logs'
import { fmt, fmtSign, fmtElapsed } from '../lib/format'
import { cn } from '../lib/cn'
import type { Stats, Job, BotStatus } from '../types'

// ── Log parsing ─────────────────────────────────────────────────────────────

interface ActivityItem { ts: string; text: string; type: 'ok' | 'error' | 'warn' | 'info' }

function parseActivity(lines: string[]): ActivityItem[] {
  const items: ActivityItem[] = []
  for (let i = lines.length - 1; i >= 0 && items.length < 15; i--) {
    const line = lines[i]
    if (!line.trim() || line.trim() === '—') continue
    const tsMatch = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/)
    const ts = tsMatch ? tsMatch[1].slice(11) : ''
    const text = line.replace(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+\s*/, '').trim()
    if (!text || text.startsWith('—')) continue
    let type: ActivityItem['type'] = 'info'
    if (/✓|complete|passed|success/i.test(text) && !/fail/i.test(text)) type = 'ok'
    else if (/✗|error|fail|blocked/i.test(text)) type = 'error'
    else if (/⚠|warn/i.test(text)) type = 'warn'
    items.unshift({ ts, text: text.slice(0, 90), type })
  }
  return items
}

// ── Main component ───────────────────────────────────────────────────────────

export function Dashboard() {
  const [stats,    setStats]    = useState<Stats | null>(null)
  const [jobs,     setJobs]     = useState<Job[]>([])
  const [bot,      setBot]      = useState<BotStatus | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    Promise.all([
      statsApi.get(),
      jobsApi.list(),
      botApi.status().catch(() => null),
      logsApi.get(100).catch(() => ({ lines: [] as string[] })),
    ]).then(([s, j, b, l]) => {
      setStats(s)
      setJobs(j)
      setBot(b)
      setActivity(parseActivity(l.lines))
    }).finally(() => setLoading(false))
  }, [])

  const running      = jobs.filter(j => j.status === 'running')
  const recentJobs   = jobs.slice(0, 6)
  const hasData      = (stats?.total ?? 0) > 0 || jobs.length > 0
  const isEmpty      = !hasData && !bot?.running

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header />
        <div className="flex items-center justify-center flex-1 gap-2 text-muted text-sm">
          <span className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin" />
          Loading…
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-5 h-11 border-b border-border bg-surface shrink-0">
        <span className="text-sm font-semibold text-text">Home</span>

        {/* System pulse */}
        {(running.length > 0 || bot?.running) ? (
          <div className="flex items-center gap-2 px-2.5 py-1 bg-amber/10 border border-amber/20 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
            <span className="text-[11px] font-semibold text-amber">
              {running.length > 0 ? `${running.length} research running` : ''}
              {running.length > 0 && bot?.running ? ' · ' : ''}
              {bot?.running ? `${bot.strategy} live` : ''}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-muted2" />
            <span className="text-[11px] text-muted2">Idle</span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          {bot?.running && (
            <Link to="/paper-trading"
              className="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold text-green border border-green/25 rounded-full hover:bg-green/10 transition-colors">
              <span className="w-1 h-1 rounded-full bg-green animate-pulse" />
              Terminal
            </Link>
          )}
          <Link to="/research"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-accent text-bg rounded-md hover:bg-accent-dim transition-colors">
            <FlaskConical size={12} />
            New Research
          </Link>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {isEmpty
          ? <EmptyCommandCenter activity={activity} />
          : <LoadedCommandCenter stats={stats} jobs={recentJobs} bot={bot} activity={activity} running={running} />
        }
      </div>
    </div>
  )
}

function Header() {
  return (
    <div className="flex items-center px-5 h-11 border-b border-border bg-surface shrink-0">
      <span className="text-sm font-semibold text-text">Home</span>
    </div>
  )
}

// ── Empty / Onboarding ───────────────────────────────────────────────────────

function EmptyCommandCenter({ activity }: { activity: ActivityItem[] }) {
  return (
    <div className="p-6 max-w-5xl">
      {/* Onboarding headline */}
      <div className="mb-8">
        <h1 className="text-xl font-bold text-text">Start finding your edge</h1>
        <p className="text-sm text-muted mt-1">Run a backtest, inspect results, then paper trade your best strategy.</p>
      </div>

      {/* Workflow steps */}
      <div className="grid grid-cols-3 gap-3 mb-8">
        <WorkflowStep
          n={1} active
          icon={<FlaskConical size={18} className="text-accent" />}
          title="Run Research"
          desc="Backtest EMACrossover across symbols, timeframes, and parameter combinations."
          cta="Start Research"
          to="/research"
        />
        <WorkflowStep
          n={2}
          icon={<BarChart2 size={18} className="text-muted2" />}
          title="Inspect Results"
          desc="Review Sharpe ratios, drawdowns, and gate decisions. Identify your top performer."
          cta="View Strategies"
          to="/strategies"
        />
        <WorkflowStep
          n={3}
          icon={<CandlestickChart size={18} className="text-muted2" />}
          title="Paper Trade"
          desc="Deploy your best strategy against live market data with simulated capital."
          cta="Launch Bot"
          to="/paper-trading"
        />
      </div>

      {/* Stats row — zeros but educational */}
      <div className="grid grid-cols-4 gap-2 mb-8">
        {[
          { label: 'Backtests Run', value: '0', note: 'run research to populate' },
          { label: 'Strategies Tested', value: '0', note: '20 configs per symbol/tf' },
          { label: 'Gate Passed', value: '0', note: 'promising + needs work' },
          { label: 'Paper Bot', value: 'Off', note: 'deploy from strategies' },
        ].map(({ label, value, note }) => (
          <div key={label} className="bg-surface border border-border rounded-lg px-4 py-3">
            <div className="text-xs text-muted mb-1">{label}</div>
            <div className="text-2xl font-bold font-mono text-muted2">{value}</div>
            <div className="text-[10px] text-muted2 mt-0.5 leading-tight">{note}</div>
          </div>
        ))}
      </div>

      {/* Activity feed */}
      {activity.length > 0 && (
        <div>
          <div className="section-label mb-3">Recent System Activity</div>
          <ActivityFeed items={activity} />
        </div>
      )}
    </div>
  )
}

function WorkflowStep({
  n, icon, title, desc, cta, to, active,
}: {
  n: number; icon: React.ReactNode; title: string; desc: string; cta: string; to: string; active?: boolean
}) {
  return (
    <div className={cn(
      'relative bg-surface border rounded-xl p-5 flex flex-col gap-3',
      active ? 'border-accent/30' : 'border-border',
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className={cn(
          'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
          active ? 'bg-accent/10' : 'bg-s3',
        )}>
          {icon}
        </div>
        <span className={cn(
          'text-[10px] font-bold rounded-full px-2 py-0.5',
          active ? 'bg-accent text-bg' : 'bg-s3 text-muted2',
        )}>
          STEP {n}
        </span>
      </div>
      <div>
        <div className="text-sm font-semibold text-text mb-1">{title}</div>
        <div className="text-xs text-muted leading-relaxed">{desc}</div>
      </div>
      <Link to={to} className={cn(
        'mt-auto flex items-center gap-1 text-xs font-semibold transition-colors',
        active ? 'text-accent hover:opacity-80' : 'text-muted hover:text-text',
      )}>
        {cta} <ChevronRight size={12} />
      </Link>
    </div>
  )
}

// ── Loaded state ─────────────────────────────────────────────────────────────

function LoadedCommandCenter({
  stats, jobs, bot, activity, running,
}: {
  stats: Stats | null
  jobs: Job[]
  bot: BotStatus | null
  activity: ActivityItem[]
  running: Job[]
}) {
  return (
    <div className="p-5 flex flex-col gap-5 max-w-6xl">
      {/* Metric strip */}
      {stats && (
        <div className="grid grid-cols-4 gap-2">
          <MetricTile
            label="Strategies Tested"
            value={stats.total ?? 0}
            note="total backtests"
          />
          <MetricTile
            label="Best Sharpe"
            value={stats.best_sharpe != null ? fmt(stats.best_sharpe, 2) : '—'}
            colorClass={stats.best_sharpe != null && stats.best_sharpe >= 1 ? 'text-green' : 'text-text'}
            note="top performer"
          />
          <MetricTile
            label="Gate Passed"
            value={(stats.promising ?? 0) + (stats.needs_imp ?? 0)}
            colorClass={(stats.promising ?? 0) + (stats.needs_imp ?? 0) > 0 ? 'text-accent' : 'text-text'}
            note="promising + needs work"
          />
          <MetricTile
            label="Paper Bot"
            value={bot?.running ? 'Live' : 'Off'}
            colorClass={bot?.running ? 'text-green' : 'text-muted'}
            pulse={bot?.running}
            note={bot?.running ? bot.strategy ?? '' : 'not running'}
          />
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid grid-cols-[1fr_280px] gap-4 items-start">
        {/* Left: recent jobs + quick actions */}
        <div className="flex flex-col gap-4">
          {/* Running jobs */}
          {running.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="section-label flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
                  Running Now
                </div>
                <Link to="/jobs" className="text-xs text-accent hover:opacity-80 flex items-center gap-0.5">
                  All jobs <ChevronRight size={11} />
                </Link>
              </div>
              <div className="flex flex-col gap-1.5">
                {running.map(j => <RunningJobRow key={j.job_id} job={j} />)}
              </div>
            </div>
          )}

          {/* Recent jobs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="section-label">Recent Research</span>
              {jobs.length > 4 && (
                <Link to="/jobs" className="text-xs text-accent hover:opacity-80 flex items-center gap-0.5">
                  All <ChevronRight size={11} />
                </Link>
              )}
            </div>
            {jobs.length === 0 ? (
              <div className="flex items-center gap-3 px-4 py-4 bg-surface border border-dashed border-border rounded-lg">
                <FlaskConical size={16} className="text-muted2 shrink-0" />
                <div>
                  <div className="text-sm text-muted">No research runs yet</div>
                  <Link to="/research" className="text-xs text-accent hover:opacity-80">Launch first backtest →</Link>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                {jobs.filter(j => j.status !== 'running').slice(0, 5).map(j => (
                  <JobRow key={j.job_id} job={j} />
                ))}
              </div>
            )}
          </div>

          {/* Bot card if running */}
          {bot?.running && <BotCard bot={bot} />}

          {/* Quick actions */}
          <div className="grid grid-cols-2 gap-2">
            <QuickAction to="/strategies"
              icon={<BarChart2 size={16} className="text-accent" />}
              label="Strategy Results"
              sub={`${stats?.total ?? 0} tested`}
            />
            <QuickAction to="/paper-trading"
              icon={<CandlestickChart size={16} className={bot?.running ? 'text-green' : 'text-muted'} />}
              label={bot?.running ? 'Trading Terminal' : 'Paper Trading'}
              sub={bot?.running ? `${bot.strategy} · live` : 'Deploy a strategy'}
              accent={bot?.running ? 'green' : undefined}
            />
          </div>
        </div>

        {/* Right: activity feed */}
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
            <Activity size={12} className="text-muted" />
            <span className="text-xs font-semibold text-muted">System Activity</span>
          </div>
          {activity.length === 0 ? (
            <div className="px-4 py-6 text-xs text-muted2 text-center">No recent activity</div>
          ) : (
            <div className="divide-y divide-border max-h-[400px] overflow-y-auto scrollbar-thin">
              {activity.map((item, i) => (
                <div key={i} className="flex items-start gap-2 px-3 py-2">
                  <ActivityIcon type={item.type} />
                  <div className="flex-1 min-w-0">
                    <div className={cn('text-[11px] leading-relaxed break-all',
                      item.type === 'ok' ? 'text-green' : item.type === 'error' ? 'text-red' : item.type === 'warn' ? 'text-amber' : 'text-muted',
                    )}>
                      {item.text}
                    </div>
                    {item.ts && (
                      <div className="text-[10px] text-muted2 font-mono mt-0.5">{item.ts}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="border-t border-border px-3 py-2">
            <Link to="/logs" className="text-[11px] text-accent hover:opacity-80 flex items-center gap-1">
              View full logs <ChevronRight size={10} />
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────────────────────

function MetricTile({
  label, value, note, colorClass, pulse,
}: {
  label: string
  value: string | number
  note?: string
  colorClass?: string
  pulse?: boolean
}) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-4">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-muted2 mb-2">{label}</div>
      <div className={cn('text-3xl font-bold font-mono tabular-nums flex items-center gap-2', colorClass ?? 'text-text')}>
        {value}
        {pulse && <span className="w-2 h-2 rounded-full bg-green animate-pulse" />}
      </div>
      {note && <div className="text-[11px] text-muted2 mt-1">{note}</div>}
    </div>
  )
}

function RunningJobRow({ job }: { job: Job }) {
  return (
    <Link
      to={`/jobs/${job.job_id}`}
      className="flex items-center gap-3 px-4 py-3 bg-amber/5 border border-amber/20 rounded-lg hover:bg-amber/10 transition-colors"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse shrink-0" />
      <span className="font-mono text-xs text-muted shrink-0">{job.job_id.slice(0, 10)}…</span>
      {job.progress_pct != null && (
        <>
          <div className="flex-1 h-1 bg-s3 rounded-full overflow-hidden">
            <div className="h-full bg-amber rounded-full transition-all" style={{ width: `${job.progress_pct}%` }} />
          </div>
          <span className="text-xs font-mono text-amber shrink-0">{job.progress_pct.toFixed(0)}%</span>
        </>
      )}
      <ArrowRight size={12} className="text-muted shrink-0" />
    </Link>
  )
}

function JobRow({ job }: { job: Job }) {
  const statusDot = ({
    done: 'bg-green',
    failed: 'bg-red',
    cancelled: 'bg-muted2',
    running: 'bg-amber animate-pulse',
    pending: 'bg-muted2',
  } as Record<string, string>)[job.status] ?? 'bg-muted2'

  return (
    <Link
      to={`/jobs/${job.job_id}`}
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface hover:border hover:border-border transition-colors group"
    >
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', statusDot)} />
      <span className="font-mono text-xs text-muted shrink-0">{job.job_id.slice(0, 10)}…</span>
      <span className="text-xs text-muted2 flex-1 min-w-0 truncate font-mono">
        {job.started_at?.slice(11, 19) ?? '—'}
      </span>
      {job.n_tested != null && (
        <span className="text-xs font-mono shrink-0">
          <span className="text-green">{job.n_passed ?? 0}</span>
          <span className="text-muted2">/{job.n_tested}</span>
        </span>
      )}
      {job.elapsed_secs != null && (
        <span className="text-[11px] text-muted2 font-mono shrink-0">{fmtElapsed(job.elapsed_secs)}</span>
      )}
      <ArrowRight size={11} className="text-muted opacity-0 group-hover:opacity-100 shrink-0 transition-opacity" />
    </Link>
  )
}

function BotCard({ bot }: { bot: BotStatus }) {
  const upnl = bot.unrealized_pnl ?? 0
  const rpnl = bot.realized_pnl ?? 0

  return (
    <div className="bg-surface border border-green/20 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green animate-pulse" />
          <span className="text-sm font-semibold text-text">{bot.strategy}</span>
          {bot.symbols?.length > 0 && (
            <span className="text-xs font-mono text-muted px-1.5 py-0.5 bg-s3 rounded">{bot.symbols.join(' · ')}</span>
          )}
        </div>
        <Link to="/paper-trading" className="text-xs font-semibold text-green hover:opacity-80 flex items-center gap-1">
          Terminal <ArrowRight size={11} />
        </Link>
      </div>
      <div className="grid grid-cols-4 gap-3">
        {[
          { l: 'Capital', v: `$${fmt(bot.capital, 0)}`, c: '' },
          { l: 'Equity', v: `$${fmt(bot.equity, 0)}`, c: '' },
          { l: 'Open P&L', v: fmtSign(upnl), c: upnl > 0 ? 'text-green' : upnl < 0 ? 'text-red' : 'text-muted' },
          { l: 'Realized', v: fmtSign(rpnl), c: rpnl > 0 ? 'text-green' : rpnl < 0 ? 'text-red' : 'text-muted' },
        ].map(({ l, v, c }) => (
          <div key={l}>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-muted2 mb-0.5">{l}</div>
            <div className={cn('text-sm font-mono font-semibold', c || 'text-text')}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function QuickAction({
  to, icon, label, sub, accent,
}: {
  to: string
  icon: React.ReactNode
  label: string
  sub: string
  accent?: 'green'
}) {
  return (
    <Link to={to} className={cn(
      'flex items-center gap-3 px-4 py-3.5 bg-surface border rounded-xl hover:bg-s2 transition-colors group',
      accent === 'green' ? 'border-green/20 hover:border-green/30' : 'border-border hover:border-border2',
    )}>
      <div className={cn(
        'w-9 h-9 rounded-lg flex items-center justify-center shrink-0',
        accent === 'green' ? 'bg-green/10' : 'bg-s3',
      )}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-text">{label}</div>
        <div className={cn('text-xs mt-0.5', accent === 'green' ? 'text-green' : 'text-muted')}>{sub}</div>
      </div>
      <ArrowRight size={13} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
    </Link>
  )
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <div className="divide-y divide-border max-h-[280px] overflow-y-auto scrollbar-thin">
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-2.5 px-4 py-2.5">
            <ActivityIcon type={item.type} />
            <div className="flex-1 min-w-0">
              <div className={cn('text-xs leading-relaxed',
                item.type === 'ok' ? 'text-green' : item.type === 'error' ? 'text-red' : item.type === 'warn' ? 'text-amber' : 'text-muted',
              )}>
                {item.text}
              </div>
              {item.ts && <div className="text-[10px] text-muted2 font-mono mt-0.5">{item.ts}</div>}
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-border px-4 py-2">
        <Link to="/logs" className="text-xs text-accent hover:opacity-80">View all logs →</Link>
      </div>
    </div>
  )
}

function ActivityIcon({ type }: { type: ActivityItem['type'] }) {
  const cls = 'w-3.5 h-3.5 shrink-0 mt-0.5'
  if (type === 'ok')    return <CheckCircle2 className={cn(cls, 'text-green')} />
  if (type === 'error') return <XCircle      className={cn(cls, 'text-red')} />
  if (type === 'warn')  return <AlertCircle  className={cn(cls, 'text-amber')} />
  return <Clock className={cn(cls, 'text-muted2')} />
}
