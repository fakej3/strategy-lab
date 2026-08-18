import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical, ArrowRight, XCircle } from 'lucide-react'
import { jobsApi } from '../api/jobs'
import { StatusBadge } from '../components/ui/Badge'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import { cn } from '../lib/cn'
import type { Job } from '../types'

export function JobQueue() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setL] = useState(true)

  const load = () => jobsApi.list().then(setJobs).finally(() => setL(false))
  useEffect(() => { load() }, [])

  async function cancel(id: string, e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    await jobsApi.cancel(id)
    load()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Jobs</span>
        <Link
          to="/research"
          className="inline-flex items-center gap-2 px-4 py-1.5 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors"
        >
          <FlaskConical size={14} />
          New Run
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <LoadingState />}

        {!loading && jobs.length === 0 && (
          <div className="p-6">
            <EmptyState
              message="No research jobs yet."
              sub="Launch a backtest from the Research page."
              action={
                <Link to="/research" className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors">
                  Start Research
                </Link>
              }
            />
          </div>
        )}

        {!loading && jobs.length > 0 && (
          <div className="p-4 flex flex-col gap-2">
            {jobs.map(j => (
              <Link
                key={j.job_id}
                to={`/jobs/${j.job_id}`}
                className={cn(
                  'flex items-center gap-4 px-4 py-3.5 bg-surface border rounded-lg hover:border-border2 hover:bg-s2 transition-colors group',
                  j.status === 'running' ? 'border-amber/30' : 'border-border',
                )}
              >
                <StatusBadge status={j.status} />

                <span className="font-mono text-xs text-muted shrink-0">{j.job_id.slice(0, 14)}…</span>

                <span className="text-sm text-muted flex-1 min-w-0 truncate">{fmtTime(j.started_at)}</span>

                {j.status === 'running' && j.progress_pct != null && (
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="w-16 h-1 bg-s3 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-amber rounded-full transition-all"
                        style={{ width: `${j.progress_pct}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-amber">{j.progress_pct.toFixed(0)}%</span>
                  </div>
                )}

                {j.n_tested != null && j.status !== 'running' && (
                  <span className="text-xs font-mono shrink-0">
                    <span className="text-green font-semibold">{j.n_passed ?? 0}</span>
                    <span className="text-muted2"> / {j.n_tested}</span>
                  </span>
                )}

                {j.elapsed_secs != null && (
                  <span className="text-xs text-muted font-mono shrink-0">{fmtElapsed(j.elapsed_secs)}</span>
                )}

                {j.status === 'running' && (
                  <button
                    onClick={e => cancel(j.job_id, e)}
                    className="shrink-0 p-1.5 text-muted hover:text-red hover:bg-red/10 rounded transition-colors"
                    title="Cancel job"
                  >
                    <XCircle size={14} />
                  </button>
                )}

                <ArrowRight size={14} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
