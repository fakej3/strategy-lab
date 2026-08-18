import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, Download, Trash2, FileText } from 'lucide-react'
import { reportsApi } from '../api/reports'
import { EmptyState, LoadingState, ErrorState } from '../components/ui/EmptyState'
import { fmt } from '../lib/format'
import { cn } from '../lib/cn'
import type { Report } from '../types'

export function Reports() {
  const [files,   setFiles]   = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

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
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Reports</span>
        <span className="text-xs text-muted">{!loading && !error ? `${files.length} report${files.length !== 1 ? 's' : ''}` : ''}</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <LoadingState />}
        {error   && <div className="p-6"><ErrorState message={error} /></div>}

        {!loading && !error && files.length === 0 && (
          <div className="p-6">
            <EmptyState
              message="No reports yet."
              sub="Reports are generated automatically when a research run completes."
              action={
                <Link to="/research" className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-bg text-sm font-semibold rounded-md hover:bg-accent-dim transition-colors">
                  Start Research
                </Link>
              }
            />
          </div>
        )}

        {!loading && files.length > 0 && (
          <div className="p-4 flex flex-col gap-2">
            {files.map(f => (
              <div
                key={f.name}
                className="flex items-center gap-4 px-4 py-3.5 bg-surface border border-border rounded-lg hover:border-border2 transition-colors"
              >
                <div className="w-8 h-8 rounded-lg bg-s3 flex items-center justify-center shrink-0">
                  <FileText size={15} className="text-muted" />
                </div>

                <div className="flex-1 min-w-0">
                  <a
                    href={reportsApi.viewUrl(f.name)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-text hover:text-accent transition-colors truncate block"
                    title={f.name}
                  >
                    {f.name}
                  </a>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-muted">{f.modified}</span>
                    {f.symbol && (
                      <span className="text-xs font-mono text-muted">
                        {f.symbol}{f.interval ? ` · ${f.interval}` : ''}
                      </span>
                    )}
                    <span className="text-xs text-muted">{f.size_kb} KB</span>
                  </div>
                </div>

                <div className="flex items-center gap-4 shrink-0">
                  {f.n_passed != null && (
                    <div className="text-right">
                      <div className="text-sm font-semibold font-mono text-green">{f.n_passed}</div>
                      <div className="text-xs text-muted">passed</div>
                    </div>
                  )}
                  {f.sharpe != null && (
                    <div className={cn('text-right', (Number(f.sharpe) >= 1) ? 'text-accent' : 'text-muted')}>
                      <div className="text-sm font-semibold font-mono">{fmt(Number(f.sharpe), 2)}</div>
                      <div className="text-xs text-muted">Sharpe</div>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0 pl-2 border-l border-border">
                  <a
                    href={reportsApi.viewUrl(f.name)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1.5 text-muted hover:text-accent rounded transition-colors"
                    title="Open report"
                  >
                    <ExternalLink size={14} />
                  </a>
                  <a
                    href={reportsApi.downloadUrl(f.name)}
                    className="p-1.5 text-muted hover:text-text rounded transition-colors"
                    title="Download"
                  >
                    <Download size={14} />
                  </a>
                  <button
                    onClick={() => deleteReport(f.name)}
                    className="p-1.5 text-muted hover:text-red rounded transition-colors"
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
