import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, Download, Trash2 } from 'lucide-react'
import { reportsApi } from '../api/reports'
import { EmptyState, LoadingState, ErrorState } from '../components/ui/EmptyState'
import type { Report } from '../types'

export function Reports() {
  const [files, setFiles]     = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

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
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Reports</span>
          <span className="ml-3 text-[10px] text-muted">Generated HTML research reports</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <div className="p-5"><LoadingState /></div>}
        {error   && <div className="p-5"><ErrorState message={error} /></div>}
        {!loading && !error && files.length === 0 && (
          <div className="p-5">
            <EmptyState
              message="No reports yet."
              action={<Link to="/research" className="text-accent text-xs hover:underline">Run research first →</Link>}
            />
          </div>
        )}
        {!loading && files.length > 0 && (
          <table className="w-full table-dense">
            <thead>
              <tr className="border-b border-border bg-surface sticky top-0">
                <th>Report</th>
                <th>Modified</th>
                <th>Market</th>
                <th className="text-right">Size</th>
                <th className="text-right">Passed</th>
                <th className="text-right">Sharpe</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {files.map(f => (
                <tr key={f.name}>
                  <td className="font-mono text-accent max-w-[280px]">
                    <a
                      href={reportsApi.viewUrl(f.name)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:underline truncate block"
                      title={f.name}
                    >
                      {f.name}
                    </a>
                  </td>
                  <td className="text-muted">{f.modified}</td>
                  <td className="font-mono text-muted">
                    {f.symbol ? `${f.symbol}${f.interval ? ` ${f.interval}` : ''}` : '—'}
                  </td>
                  <td className="text-right font-mono text-muted">{f.size_kb} KB</td>
                  <td className="text-right font-mono">
                    {f.n_passed != null ? <span className="text-green">{f.n_passed}</span> : '—'}
                  </td>
                  <td className="text-right font-mono">
                    {f.sharpe != null ? Number(f.sharpe).toFixed(3) : '—'}
                  </td>
                  <td>
                    <div className="flex items-center gap-2 justify-end">
                      <a
                        href={reportsApi.viewUrl(f.name)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted hover:text-accent transition-colors"
                        title="Open"
                      >
                        <ExternalLink size={12} />
                      </a>
                      <a
                        href={reportsApi.downloadUrl(f.name)}
                        className="text-muted hover:text-text transition-colors"
                        title="Download"
                      >
                        <Download size={12} />
                      </a>
                      <button
                        onClick={() => deleteReport(f.name)}
                        className="text-muted hover:text-red transition-colors"
                        title="Delete"
                      >
                        <Trash2 size={12} />
                      </button>
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
