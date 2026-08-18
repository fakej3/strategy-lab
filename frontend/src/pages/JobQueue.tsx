import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical, ArrowRight, XCircle, ChevronRight } from 'lucide-react'
import { jobsApi } from '../api/jobs'
import { fmtElapsed } from '../lib/format'
import { cn } from '../lib/cn'
import type { Job } from '../types'

type Filter = 'all' | 'running' | 'done' | 'failed'

function statusDot(status: string) {
  return {
    done:      'bg-green',
    failed:    'bg-red',
    cancelled: 'bg-muted2',
    running:   'bg-amber animate-pulse',
  }[status] ?? 'bg-muted2'
}

function statusLabel(status: string) {
  return { done: 'Done', failed: 'Failed', cancelled: 'Cancelled', running: 'Running' }[status] ?? status
}

export function JobQueue() {
  const [jobs,   setJobs]   = useState<Job[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [loading, setL]     = useState(true)

  const load = () => jobsApi.list().then(setJobs).finally(() => setL(false))
  useEffect(() => { load() }, [])

  async function cancel(id: string, e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    await jobsApi.cancel(id)
    load()
  }

  const counts = {
    all:     jobs.length,
    running: jobs.filter(j => j.status === 'running').length,
    done:    jobs.filter(j => j.status === 'done').length,
    failed:  jobs.filter(j => ['failed', 'cancelled'].includes(j.status)).length,
  }

  const visible = filter === 'all' ? jobs
    : filter === 'failed' ? jobs.filter(j => ['failed', 'cancelled'].includes(j.status))
    : jobs.filter(j => j.status === filter)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-11 border-b border-border bg-surface shrink-0">
        <span className="text-sm font-semibold text-text">Research Jobs</span>
        <Link
          to="/research"
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-bg text-xs font-semibold rounded-md hover:bg-accent-dim transition-colors"
        >
          <FlaskConical size={12} />
          New Run
        </Link>
      </div>

      {/* Status tabs */}
      {!loading && jobs.length > 0 && (
        <div className="flex items-center gap-0.5 px-5 py-2.5 border-b border-border">
          {(['all', 'running', 'done', 'failed'] as Filter[]).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize',
                filter === f
                  ? 'bg-s3 text-text'
                  : 'text-muted hover:text-text hover:bg-s2',
              )}
            >
              {f}
              {counts[f] > 0 && (
                <span className={cn(
                  'inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full text-[10px] font-semibold',
                  f === 'running' && counts.running > 0 ? 'bg-amber/20 text-amber'
                  : f === 'failed' && counts.failed > 0 ? 'bg-red/15 text-red'
                  : f === 'done' && counts.done > 0 ? 'bg-green/15 text-green'
                  : 'bg-s3 text-muted2',
                )}>
                  {counts[f]}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-16 text-muted text-sm">
            <span className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin" />
            Loading…
          </div>
        )}

        {!loading && jobs.length === 0 && (
          <div className="max-w-lg mx-auto px-6 py-16">
            <div className="text-center mb-8">
              <div className="w-12 h-12 rounded-xl bg-s2 border border-border flex items-center justify-center mx-auto mb-4">
                <FlaskConical size={20} className="text-muted2" />
              </div>
              <h2 className="text-base font-semibold text-text mb-1">No research runs yet</h2>
              <p className="text-sm text-muted">Launch a backtest to see results here.</p>
            </div>

            {/* Mini workflow */}
            <div className="flex items-center gap-2 justify-center mb-6 text-xs text-muted">
              <span>Configure</span>
              <ChevronRight size={12} />
              <span>Run backtest</span>
              <ChevronRight size={12} />
              <span>Review results</span>
              <ChevronRight size={12} />
              <span>Deploy</span>
            </div>

            <div className="flex justify-center">
              <Link
                to="/research"
                className="flex items-center gap-2 px-5 py-2.5 bg-accent text-bg text-sm font-semibold rounded-lg hover:bg-accent-dim transition-colors"
              >
                <FlaskConical size={14} />
                Start Research
              </Link>
            </div>
          </div>
        )}

        {!loading && jobs.length > 0 && visible.length === 0 && (
          <div className="flex items-center justify-center py-12 text-muted text-sm">
            No {filter} jobs
          </div>
        )}

        {!loading && visible.length > 0 && (
          <div className="p-4 flex flex-col gap-1.5">
            {visible.map(j => (
              <Link
                key={j.job_id}
                to={`/jobs/${j.job_id}`}
                className={cn(
                  'flex items-center gap-3 px-4 py-3 bg-surface border rounded-xl hover:bg-s2 transition-colors group',
                  j.status === 'running' ? 'border-amber/25 hover:border-amber/40' : 'border-border hover:border-border2',
                )}
              >
                <span className={cn('w-2 h-2 rounded-full shrink-0', statusDot(j.status))} />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs text-muted">{j.job_id.slice(0, 12)}…</span>
                    <span className={cn(
                      'text-[10px] font-semibold',
                      j.status === 'done' ? 'text-green' : j.status === 'failed' ? 'text-red' : j.status === 'running' ? 'text-amber' : 'text-muted2',
                    )}>
                      {statusLabel(j.status)}
                    </span>
                  </div>
                  <div className="text-xs text-muted2 font-mono mt-0.5">
                    {j.started_at?.slice(0, 19).replace('T', ' ') ?? '—'}
                  </div>
                </div>

                {/* Progress bar for running */}
                {j.status === 'running' && j.progress_pct != null && (
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="w-20 h-1 bg-s3 rounded-full overflow-hidden">
                      <div className="h-full bg-amber rounded-full transition-all" style={{ width: `${j.progress_pct}%` }} />
                    </div>
                    <span className="text-xs font-mono text-amber w-8">{j.progress_pct.toFixed(0)}%</span>
                  </div>
                )}

                {/* Result summary for done */}
                {j.n_tested != null && j.status !== 'running' && (
                  <div className="shrink-0 text-right">
                    <div className="text-xs font-mono">
                      <span className="text-green font-semibold">{j.n_passed ?? 0}</span>
                      <span className="text-muted2"> / {j.n_tested} passed</span>
                    </div>
                    {j.elapsed_secs != null && (
                      <div className="text-[10px] text-muted2 font-mono">{fmtElapsed(j.elapsed_secs)}</div>
                    )}
                  </div>
                )}

                {j.status === 'running' && (
                  <button
                    onClick={e => cancel(j.job_id, e)}
                    className="shrink-0 p-1.5 text-muted hover:text-red hover:bg-red/10 rounded-lg transition-colors"
                    title="Cancel"
                  >
                    <XCircle size={13} />
                  </button>
                )}

                <ArrowRight size={13} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
