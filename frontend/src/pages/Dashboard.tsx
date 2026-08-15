import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical, TrendingUp, ArrowRight } from 'lucide-react'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { StatusBadge } from '../components/ui/Badge'
import { LoadingState } from '../components/ui/EmptyState'
import { fmt, fmtTime, fmtElapsed } from '../lib/format'
import { cn } from '../lib/cn'
import type { Stats, Job } from '../types'

export function Dashboard() {
  const [stats, setStats]     = useState<Stats | null>(null)
  const [jobs, setJobs]       = useState<Job[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([statsApi.get(), jobsApi.list()])
      .then(([s, j]) => { setStats(s); setJobs(j) })
      .finally(() => setLoading(false))
  }, [])

  const running = jobs.filter(j => j.status === 'running')
  const recent  = jobs.slice(0, 10)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Dashboard</span>
          <span className="ml-3 text-[10px] text-muted">Research engine overview</span>
        </div>
        <Link
          to="/research"
          className="inline-flex items-center gap-1.5 px-3 py-1 bg-accent text-bg text-[11px] font-semibold rounded transition-colors hover:bg-accent-dim"
        >
          <FlaskConical size={11} />
          New Run
        </Link>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* Running alert */}
        {running.length > 0 && (
          <div className="flex items-center gap-2 px-5 py-2 border-b border-amber/20 bg-amber/5">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber animate-pulse shrink-0" />
            <span className="text-amber text-[11px]">
              {running.length} job{running.length > 1 ? 's' : ''} running
            </span>
            <Link to="/jobs" className="ml-auto text-[10px] font-semibold text-amber flex items-center gap-0.5 hover:underline">
              View <ArrowRight size={9} />
            </Link>
          </div>
        )}

        {loading ? (
          <div className="p-5"><LoadingState /></div>
        ) : (
          <>
            {/* Stats row */}
            {stats && (
              <div className="grid grid-cols-6 border-b border-border">
                <Stat label="Total Results" value={stats.total ?? 0} />
                <Stat label="Gate Passed"   value={(stats.promising ?? 0) + (stats.needs_imp ?? 0)} positive />
                <Stat label="Rejected"      value={stats.rejected ?? 0} negative={(stats.rejected ?? 0) > 0} />
                <Stat label="Best Sharpe"   value={stats.best_sharpe != null ? fmt(stats.best_sharpe, 3) : '—'} accent icon={<TrendingUp size={10} />} />
                <Stat label="Avg Sharpe"    value={stats.avg_sharpe  != null ? fmt(stats.avg_sharpe, 3)  : '—'} />
                <Stat label="Running"       value={running.length} pulse={running.length > 0} />
              </div>
            )}

            {/* Recent jobs table */}
            {recent.length > 0 ? (
              <div>
                <div className="flex items-center justify-between px-5 py-2 border-b border-border">
                  <span className="section-label">Recent Jobs</span>
                  <Link to="/jobs" className="text-[9px] text-accent hover:underline flex items-center gap-0.5">
                    All jobs <ArrowRight size={8} />
                  </Link>
                </div>
                <table className="w-full table-dense">
                  <thead>
                    <tr className="border-b border-border bg-surface">
                      <th>Job ID</th>
                      <th>Status</th>
                      <th>Started</th>
                      <th className="text-right">Tested</th>
                      <th className="text-right">Passed</th>
                      <th className="text-right">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map(j => (
                      <tr key={j.job_id}>
                        <td className="font-mono text-accent">
                          <Link to={`/jobs/${j.job_id}`} className="hover:underline">{j.job_id.slice(0, 16)}</Link>
                        </td>
                        <td><StatusBadge status={j.status} /></td>
                        <td className="text-muted">{fmtTime(j.started_at)}</td>
                        <td className="text-right font-mono">{j.n_tested}</td>
                        <td className="text-right font-mono text-green">{j.n_passed}</td>
                        <td className="text-right font-mono text-muted">{fmtElapsed(j.elapsed_secs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 m-5 py-16 border border-dashed border-border">
                <FlaskConical size={22} className="text-muted2" />
                <p className="text-[12px] text-text font-medium">No research runs yet</p>
                <p className="text-[10px] text-muted">Run a backtest to see results here</p>
                <Link
                  to="/research"
                  className="mt-1 inline-flex items-center gap-1.5 px-3 py-1 bg-accent text-bg text-[11px] font-semibold rounded hover:bg-accent-dim transition-colors"
                >
                  <FlaskConical size={11} />
                  Start Research
                </Link>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Stat({
  label, value, accent, positive, negative, pulse, icon,
}: {
  label: string
  value: string | number
  accent?: boolean
  positive?: boolean
  negative?: boolean
  pulse?: boolean
  icon?: React.ReactNode
}) {
  return (
    <div className="px-5 py-3 border-r border-border last:border-0">
      <div className="flex items-center gap-1 mb-1">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-muted">{label}</span>
        {icon && <span className="text-muted opacity-60">{icon}</span>}
        {pulse && <span className="ml-auto inline-block w-1.5 h-1.5 rounded-full bg-green animate-pulse" />}
      </div>
      <div className={cn(
        'text-[18px] font-bold font-mono tabular-nums leading-none',
        accent   && 'text-accent',
        positive && 'text-green',
        negative && 'text-red',
        !accent && !positive && !negative && 'text-text',
      )}>
        {value}
      </div>
    </div>
  )
}
