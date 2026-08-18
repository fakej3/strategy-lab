import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock, TrendingUp } from 'lucide-react'
import { historyApi } from '../api/history'
import { StatusBadge } from '../components/ui/Badge'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import { cn } from '../lib/cn'
import type { Session } from '../types'

export function History() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    historyApi.list(50).then(setSessions).finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Session History</span>
        {!loading && sessions.length > 0 && (
          <span className="text-xs text-muted">{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <LoadingState />}

        {!loading && sessions.length === 0 && (
          <div className="p-6">
            <EmptyState
              message="No sessions yet."
              sub="Completed research sessions will appear here."
              action={
                <Link to="/research" className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors">
                  Start Research
                </Link>
              }
            />
          </div>
        )}

        {!loading && sessions.length > 0 && (
          <div className="p-4 flex flex-col gap-2">
            {sessions.map(s => (
              <div
                key={s.session_id}
                className="flex items-center gap-4 px-4 py-3.5 bg-surface border border-border rounded-lg hover:border-border2 transition-colors"
              >
                <div className="w-8 h-8 rounded-lg bg-s3 flex items-center justify-center shrink-0">
                  <Clock size={14} className="text-muted" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="font-mono text-sm text-text">{s.session_id.slice(0, 24)}…</div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-muted">{fmtTime(s.started_at)}</span>
                    <StatusBadge status={s.status} />
                  </div>
                </div>

                <div className="flex items-center gap-6 shrink-0">
                  {s.n_strategies_run != null && (
                    <div className="text-right">
                      <div className="text-sm font-semibold font-mono text-text">{s.n_strategies_run}</div>
                      <div className="text-xs text-muted">tested</div>
                    </div>
                  )}
                  {s.n_passed != null && (
                    <div className="text-right">
                      <div className={cn('text-sm font-semibold font-mono', s.n_passed > 0 ? 'text-green' : 'text-muted')}>
                        {s.n_passed}
                      </div>
                      <div className="text-xs text-muted">passed</div>
                    </div>
                  )}
                  {s.elapsed_secs != null && (
                    <div className="text-right">
                      <div className="text-sm font-mono text-muted">{fmtElapsed(s.elapsed_secs)}</div>
                      <div className="text-xs text-muted">duration</div>
                    </div>
                  )}
                </div>
              </div>
            ))}

            <div className="flex items-center gap-2 px-4 py-3 text-xs text-muted">
              <TrendingUp size={12} />
              {sessions.length} session{sessions.length !== 1 ? 's' : ''} total
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
