import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { statsApi } from '../api/stats'
import { jobsApi } from '../api/jobs'
import { MetricTile } from '../components/ui/MetricTile'
import { StatusBadge } from '../components/ui/Badge'
import { LoadingState } from '../components/ui/EmptyState'
import { fmt, fmtTime, fmtElapsed } from '../lib/format'
import type { Stats, Job } from '../types'

export function Dashboard() {
  const [stats, setStats]   = useState<Stats | null>(null)
  const [jobs, setJobs]     = useState<Job[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([statsApi.get(), jobsApi.list()])
      .then(([s, j]) => { setStats(s); setJobs(j) })
      .finally(() => setLoading(false))
  }, [])

  const running = jobs.filter(j => j.status === 'running')
  const recent  = jobs.slice(0, 5)

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Dashboard</h1>
      <p className="text-[12px] text-muted mb-5">Research engine overview</p>

      {running.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-2.5 mb-5 bg-amber/10 border border-amber/30 rounded-md text-amber text-[12px]">
          <span className="inline-block w-2 h-2 rounded-full bg-amber animate-pulse" />
          {running.length} job{running.length > 1 ? 's' : ''} running —{' '}
          <Link to="/jobs" className="font-semibold underline underline-offset-2">View progress →</Link>
        </div>
      )}

      {loading ? <LoadingState /> : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
            <MetricTile label="Total Results"  value={stats?.total ?? 0} />
            <MetricTile label="Passed Gate"    value={(stats?.promising ?? 0) + (stats?.needs_imp ?? 0)} />
            <MetricTile label="Rejected"       value={stats?.rejected ?? 0} />
            <MetricTile label="Best Sharpe"    value={stats?.best_sharpe != null ? fmt(stats.best_sharpe, 3) : '—'} />
            <MetricTile label="Avg Sharpe"     value={stats?.avg_sharpe  != null ? fmt(stats.avg_sharpe,  3) : '—'} />
            <MetricTile label="Running Now"    value={running.length} positive={running.length > 0} />
          </div>

          <h2 className="text-[13px] font-semibold text-text mb-3">Quick Actions</h2>
          <div className="flex gap-2 flex-wrap mb-6">
            {[
              { to: '/research',   label: 'New Research Run', primary: true },
              { to: '/reports',    label: 'Reports' },
              { to: '/history',    label: 'Session History' },
              { to: '/strategies', label: 'Strategy Results' },
              { to: '/bot',        label: 'Paper Trading' },
            ].map(({ to, label, primary }) => (
              <Link
                key={to}
                to={to}
                className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                  primary
                    ? 'bg-accent text-bg hover:bg-accent-dim'
                    : 'bg-s2 border border-border text-text hover:bg-s3'
                }`}
              >
                {label}
              </Link>
            ))}
          </div>

          {recent.length > 0 && (
            <>
              <h2 className="text-[13px] font-semibold text-text mb-3">Recent Jobs</h2>
              <div className="bg-surface border border-border rounded-md overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b border-border">
                      {['Job ID', 'Started', 'Status', 'Tested', 'Passed', 'Duration'].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map(j => (
                      <tr key={j.job_id} className="border-b border-border last:border-0 hover:bg-s2 transition-colors">
                        <td className="px-3 py-2 font-mono text-accent">
                          <Link to={`/jobs/${j.job_id}`}>{j.job_id.slice(0, 16)}</Link>
                        </td>
                        <td className="px-3 py-2 text-muted">{fmtTime(j.started_at)}</td>
                        <td className="px-3 py-2"><StatusBadge status={j.status} /></td>
                        <td className="px-3 py-2 text-right font-mono">{j.n_tested}</td>
                        <td className="px-3 py-2 text-right font-mono">{j.n_passed}</td>
                        <td className="px-3 py-2 text-right font-mono text-muted">{fmtElapsed(j.elapsed_secs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
