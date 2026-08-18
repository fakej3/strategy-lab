import { useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { logsApi } from '../api/logs'
import { cn } from '../lib/cn'

function lineClass(line: string): string {
  if (line.includes('✓') || /\bok\b/.test(line.toLowerCase())) return 'log-line-ok'
  if (line.includes('⚠') || /warn/.test(line.toLowerCase())) return 'log-line-warn'
  if (line.includes('✗') || /error/.test(line.toLowerCase())) return 'log-line-error'
  if (line.includes('STEP')) return 'log-line-step'
  return 'log-line-muted'
}

const LINE_COUNTS = [200, 500, 2000]

export function Logs() {
  const [lines, setLines]     = useState<string[]>([])
  const [count, setCount]     = useState(200)
  const [loading, setLoading] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  const load = (n: number) => {
    setLoading(true)
    logsApi.get(n)
      .then(d => { setLines(d.lines); setCount(n) })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(200) }, [])

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [lines])

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <div className="flex items-center gap-3">
          <span className="page-title">Logs</span>
          <span className="text-xs text-muted">{lines.length} lines</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="flex rounded-md overflow-hidden border border-border">
            {LINE_COUNTS.map(n => (
              <button
                key={n}
                onClick={() => load(n)}
                className={cn(
                  'px-3 py-1.5 text-xs font-mono transition-colors',
                  count === n
                    ? 'bg-accent text-bg font-semibold'
                    : 'bg-surface text-muted hover:text-text hover:bg-s2'
                )}
              >
                {n}
              </button>
            ))}
          </div>
          <button
            onClick={() => load(count)}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted hover:text-text bg-surface border border-border rounded-md transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      <div
        ref={boxRef}
        className="flex-1 overflow-y-auto scrollbar-thin bg-bg px-4 py-3"
      >
        {lines.length === 0 ? (
          <div className="text-muted text-xs font-mono py-4">Log file is empty or not found.</div>
        ) : lines.map((line, i) => (
          <div
            key={i}
            className={cn('font-mono text-xs leading-relaxed break-all py-px', lineClass(line))}
          >
            {line || ' '}
          </div>
        ))}
      </div>
    </div>
  )
}
