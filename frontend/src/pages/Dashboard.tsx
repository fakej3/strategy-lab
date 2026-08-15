import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical, FileText, Clock, BarChart2, CandlestickChart, ArrowRight, TrendingUp } from 'lucide-react'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { MetricTile } from '../components/ui/MetricTile'
import { StatusBadge } from '../components/ui/Badge'
import { LoadingState } from '../components/ui/EmptyState'
import { fmt, fmtTime, fmtElapsed } from '../lib/format'
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
  const recent  = jobs.slice(0, 6)

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="flex items-center justify-between px-6 h-[48px] border-b border-border shrink-0">
        <div>
          <h1 className="text-[13px] font-semibold text-text leading-none">Dashboard</h1>
          <p className="text-[10px] text-muted mt-0.5 leading-none">Research engine overview</p>
        </div>
        <Link
          to="/research"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[11px] font-semibold rounded-md hover:bg-accent-dim transition-colors shadow-sm"
        >
          <FlaskConical size={12} />
          New Run
        </Link>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto scrollbar-thin p-6">
        {running.length > 0 && (
          <div className="flex items-center gap-2.5 px-3.5 py-2.5 mb-5 bg-amber/8 border border-amber/20 rounded-md">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber animate-pulse shrink-0" />
            <span className="text-amber text-[12px]">
              {running.length} job{running.length > 1 ? 's' : ''} currently running
            </span>
            <Link to="/jobs" className="ml-auto text-[11px] font-semibold text-amber flex items-center gap-1 hover:underline">
              View jobs <ArrowRight size={10} />
            </Link>
          </div>
        )}

        {loading ? <LoadingState /> : (
          <>
            {/* KPI row */}
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 mb-6">
              <MetricTile label="Total Results" value={stats?.total ?? 0} />
              <MetricTile
                label="Gate Passed"
                value={(stats?.promising ?? 0) + (stats?.needs_imp ?? 0)}
                positive={(stats?.promising ?? 0) > 0}
              />
              <MetricTile label="Rejected" value={stats?.rejected ?? 0} negative={(stats?.rejected ?? 0) > 0} />
              <MetricTile
                label="Best Sharpe"
                value={stats?.best_sharpe != null ? fmt(stats.best_sharpe, 3) : '—'}
                accent={stats?.best_sharpe != null}
                icon={<TrendingUp size={12} />}
              />
              <MetricTile
                label="Avg Sharpe"
                value={stats?.avg_sharpe != null ? fmt(stats.avg_sharpe, 3) : '—'}
              />
              <MetricTile
                label="Running Now"
                value={running.length}
                pulse={running.length > 0}
                positive={running.length > 0}
              />
            </div>

            {/* Quick nav */}
            <div className="mb-6">
              <h2 className="text-[10px] font-semibold uppercase tracking-widest text-muted2 mb-3">Quick Access</h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { to: '/reports',      icon: FileText,         label: 'Reports',      sub: 'HTML strategy reports' },
                  { to: '/history',      icon: Clock,            label: 'Run History',  sub: 'Past research sessions' },
                  { to: '/strategies',   icon: BarChart2,        label: 'Strategies',   sub: 'All backtest results' },
                  { to: '/paper-trading', icon: CandlestickChart, label: 'Paper Trading', sub: 'Live strategy bot' },
                ].map(({ to, icon: Icon, label, sub }) => (
                  <Link
                    key={to}
                    to={to}
                    className="flex items-center gap-3 px-3.5 py-3 bg-surface border border-border rounded-md hover:border-border2 hover:bg-s2 transition-all group"
                  >
                    <Icon size={16} className="text-muted group-hover:text-accent transition-colors shrink-0" />
                    <div>
                      <div className="text-[12px] font-medium text-text">{label}</div>
                      <div className="text-[10px] text-muted">{sub}</div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>

            {/* Recent jobs */}
            {recent.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[10px] font-semibold uppercase tracking-widest text-muted2">Recent Jobs</h2>
                  <Link to="/jobs" className="text-[10px] text-accent hover:underline flex items-center gap-0.5">
                    View all <ArrowRight size={9} />
                  </Link>
                </div>
                <div className="bg-surface border border-border rounded-md overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-border">
                        {['Job ID', 'Started', 'Status', 'Tested', 'Passed', 'Duration'].map(h => (
                          <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-muted">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {recent.map(j => (
                        <tr key={j.job_id} className="border-b border-border last:border-0 hover:bg-s2 transition-colors">
                          <td className="px-3 py-2 font-mono text-[11px] text-accent">
                            <Link to={`/jobs/${j.job_id}`} className="hover:underline">{j.job_id.slice(0, 14)}</Link>
                          </td>
                          <td className="px-3 py-2 text-[11px] text-muted">{fmtTime(j.started_at)}</td>
                          <td className="px-3 py-2"><StatusBadge status={j.status} /></td>
                          <td className="px-3 py-2 text-right font-mono text-[11px] text-text">{j.n_tested}</td>
                          <td className="px-3 py-2 text-right font-mono text-[11px] text-green">{j.n_passed}</td>
                          <td className="px-3 py-2 text-right font-mono text-[11px] text-muted">{fmtElapsed(j.elapsed_secs)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {recent.length === 0 && !loading && (
              <div className="flex flex-col items-center gap-2 py-12 border border-dashed border-border rounded-md">
                <FlaskConical size={28} className="text-muted2" />
                <p className="text-[13px] text-text font-medium">No research runs yet</p>
                <p className="text-[11px] text-muted">Run your first backtest to see results here</p>
                <Link
                  to="/research"
                  className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[11px] font-semibold rounded-md hover:bg-accent-dim transition-colors"
                >
                  <FlaskConical size={12} />
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
