import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { historyApi } from '../api/history'
import { StatusBadge } from '../components/ui/Badge'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import type { Session } from '../types'

export function History() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    historyApi.list(50).then(setSessions).finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex flex-col h-full">
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Session History</span>
          <span className="ml-3 text-[10px] text-muted">All completed research sessions</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <div className="p-5"><LoadingState /></div>}
        {!loading && sessions.length === 0 && (
          <div className="p-5">
            <EmptyState
              message="No sessions yet."
              action={<Link to="/research" className="text-accent text-xs hover:underline">Run research first →</Link>}
            />
          </div>
        )}
        {!loading && sessions.length > 0 && (
          <table className="w-full table-dense">
            <thead>
              <tr className="border-b border-border bg-surface sticky top-0">
                <th>Session ID</th>
                <th>Started</th>
                <th>Status</th>
                <th className="text-right">Tested</th>
                <th className="text-right">Passed</th>
                <th className="text-right">Duration</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map(s => (
                <tr key={s.session_id}>
                  <td className="font-mono text-muted">{s.session_id.slice(0, 20)}</td>
                  <td className="text-muted">{fmtTime(s.started_at)}</td>
                  <td><StatusBadge status={s.status} /></td>
                  <td className="text-right font-mono">{s.n_strategies_run}</td>
                  <td className="text-right font-mono text-green">{s.n_passed}</td>
                  <td className="text-right font-mono text-muted">{fmtElapsed(s.elapsed_secs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
