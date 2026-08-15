import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { jobsApi } from '../api/jobs'
import { StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import type { Job } from '../types'

export function JobQueue() {
  const [jobs, setJobs]   = useState<Job[]>([])
  const [loading, setL]   = useState(true)

  const load = () => jobsApi.list().then(setJobs).finally(() => setL(false))
  useEffect(() => { load() }, [])

  async function cancel(id: string) {
    await jobsApi.cancel(id)
    load()
  }

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Job Queue</h1>
      <p className="text-[12px] text-muted mb-5">All research jobs — running, completed, and failed</p>

      <div className="mb-4">
        <Link to="/research" className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-[12px] font-semibold bg-accent text-bg hover:bg-accent-dim transition-colors">
          New Research Run
        </Link>
      </div>

      {loading && <LoadingState />}
      {!loading && jobs.length === 0 && (
        <EmptyState message="No jobs yet." action={<Link to="/research" className="text-accent text-sm hover:underline">Start a research run →</Link>} />
      )}
      {!loading && jobs.length > 0 && (
        <div className="bg-surface border border-border rounded-md overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border">
                {['Job ID', 'Status', 'Started', 'Finished', 'Tested', 'Passed', 'Duration', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.job_id} className="border-b border-border last:border-0 hover:bg-s2">
                  <td className="px-3 py-2 font-mono text-accent">
                    <Link to={`/jobs/${j.job_id}`}>{j.job_id.slice(0, 16)}</Link>
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={j.status} /></td>
                  <td className="px-3 py-2 text-muted">{fmtTime(j.started_at)}</td>
                  <td className="px-3 py-2 text-muted">{fmtTime(j.finished_at)}</td>
                  <td className="px-3 py-2 text-right font-mono">{j.n_tested}</td>
                  <td className="px-3 py-2 text-right font-mono">{j.n_passed}</td>
                  <td className="px-3 py-2 text-right font-mono text-muted">{fmtElapsed(j.elapsed_secs)}</td>
                  <td className="px-3 py-2">
                    <div className="flex gap-1.5">
                      <Link to={`/jobs/${j.job_id}`} className="px-2 py-0.5 rounded bg-s2 border border-border text-[10px] text-text hover:bg-s3">
                        View
                      </Link>
                      {j.status === 'running' && (
                        <Button variant="danger" size="xs" onClick={() => cancel(j.job_id)}>Cancel</Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
