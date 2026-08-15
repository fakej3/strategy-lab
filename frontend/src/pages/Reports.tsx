import { useEffect, useState } from 'react'
import { reportsApi } from '../api/reports'
import { EmptyState, LoadingState, ErrorState } from '../components/ui/EmptyState'
import { Button } from '../components/ui/Button'
import { Link } from 'react-router-dom'
import type { Report } from '../types'

export function Reports() {
  const [files, setFiles]   = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  const load = () =>
    reportsApi.list()
      .then(setFiles)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  function deleteReport(name: string) {
    if (!confirm(`Delete ${name}?`)) return
    reportsApi.delete(name).then(load)
  }

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Reports</h1>
      <p className="text-[12px] text-muted mb-5">Generated HTML research reports</p>

      {loading && <LoadingState />}
      {error   && <ErrorState message={error} />}
      {!loading && !error && files.length === 0 && (
        <EmptyState message="No reports yet." action={<Link to="/research" className="text-accent text-sm hover:underline">Run research first →</Link>} />
      )}
      {!loading && files.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {files.map(f => (
            <div key={f.name} className="bg-surface border border-border rounded-md p-4 flex flex-col gap-2 hover:border-border2 transition-colors">
              <div className="font-semibold text-[12px] text-text truncate" title={f.name}>{f.name}</div>
              <div className="flex gap-2 text-[10px] text-muted flex-wrap">
                <span>{f.modified}</span>
                {f.symbol && <span>· {f.symbol}{f.interval ? ` ${f.interval}` : ''}</span>}
                <span>· {f.size_kb} KB</span>
              </div>
              {f.n_passed != null && (
                <div className="flex gap-2 items-center">
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-green/15 text-green border border-green/30 font-semibold">{f.n_passed} passed</span>
                  {f.sharpe != null && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30 font-semibold">Sharpe {Number(f.sharpe).toFixed(3)}</span>
                  )}
                </div>
              )}
              <div className="flex gap-2 mt-1 flex-wrap">
                <a href={reportsApi.viewUrl(f.name)} target="_blank" rel="noopener noreferrer"
                   className="px-2.5 py-1 text-[11px] rounded bg-accent text-bg font-semibold hover:bg-accent-dim transition-colors">
                  Open
                </a>
                <a href={reportsApi.downloadUrl(f.name)}
                   className="px-2.5 py-1 text-[11px] rounded bg-s2 border border-border text-text hover:bg-s3 transition-colors">
                  Download
                </a>
                <Button variant="danger" size="sm" onClick={() => deleteReport(f.name)}>Delete</Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
