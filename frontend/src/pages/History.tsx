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
    <div className="p-6 max-w-5xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Session History</h1>
      <p className="text-[12px] text-muted mb-5">All completed research sessions</p>

      {loading && <LoadingState />}
      {!loading && sessions.length === 0 && (
        <EmptyState message="No sessions yet." action={<Link to="/research" className="text-accent text-sm hover:underline">Run research first →</Link>} />
      )}
      {!loading && sessions.length > 0 && (
        <div className="bg-surface border border-border rounded-md overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border">
                {['Session ID', 'Started', 'Status', 'Tested', 'Passed', 'Duration'].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sessions.map(s => (
                <tr key={s.session_id} className="border-b border-border last:border-0 hover:bg-s2">
                  <td className="px-3 py-2 font-mono text-muted">{s.session_id.slice(0, 16)}</td>
                  <td className="px-3 py-2 text-muted">{fmtTime(s.started_at)}</td>
                  <td className="px-3 py-2"><StatusBadge status={s.status} /></td>
                  <td className="px-3 py-2 text-right font-mono">{s.n_strategies_run}</td>
                  <td className="px-3 py-2 text-right font-mono">{s.n_passed}</td>
                  <td className="px-3 py-2 text-right font-mono text-muted">{fmtElapsed(s.elapsed_secs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
