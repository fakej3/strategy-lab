import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical } from 'lucide-react'
import { jobsApi } from '../api/jobs'
import { StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import type { Job } from '../types'

export function JobQueue() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setL] = useState(true)

  const load = () => jobsApi.list().then(setJobs).finally(() => setL(false))
  useEffect(() => { load() }, [])

  async function cancel(id: string) {
    await jobsApi.cancel(id)
    load()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Job Queue</span>
          <span className="ml-3 text-[10px] text-muted">Research jobs — running, completed, failed</span>
        </div>
        <Link
          to="/research"
          className="inline-flex items-center gap-1.5 px-3 py-1 bg-accent text-bg text-[11px] font-semibold rounded hover:bg-accent-dim transition-colors"
        >
          <FlaskConical size={11} />
          New Run
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <div className="p-5"><LoadingState /></div>}
        {!loading && jobs.length === 0 && (
          <div className="p-5">
            <EmptyState message="No jobs yet." action={<Link to="/research" className="text-accent text-xs hover:underline">Start a research run →</Link>} />
          </div>
        )}
        {!loading && jobs.length > 0 && (
          <table className="w-full table-dense">
            <thead>
              <tr className="border-b border-border bg-surface sticky top-0">
                <th>Job ID</th>
                <th>Status</th>
                <th>Started</th>
                <th>Finished</th>
                <th className="text-right">Tested</th>
                <th className="text-right">Passed</th>
                <th className="text-right">Duration</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.job_id}>
                  <td className="font-mono text-accent">
                    <Link to={`/jobs/${j.job_id}`} className="hover:underline">{j.job_id.slice(0, 16)}</Link>
                  </td>
                  <td><StatusBadge status={j.status} /></td>
                  <td className="text-muted">{fmtTime(j.started_at)}</td>
                  <td className="text-muted">{fmtTime(j.finished_at)}</td>
                  <td className="text-right font-mono">{j.n_tested}</td>
                  <td className="text-right font-mono text-green">{j.n_passed}</td>
                  <td className="text-right font-mono text-muted">{fmtElapsed(j.elapsed_secs)}</td>
                  <td>
                    <div className="flex gap-1 justify-end">
                      <Link to={`/jobs/${j.job_id}`} className="px-2 py-0.5 text-[9px] font-semibold text-muted border border-border hover:border-border2 hover:text-text transition-colors">
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
        )}
      </div>
    </div>
  )
}
