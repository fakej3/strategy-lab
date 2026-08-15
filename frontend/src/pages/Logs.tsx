import { useEffect, useRef, useState } from 'react'
import { logsApi } from '../api/logs'
import { Button } from '../components/ui/Button'

function lineClass(line: string): string {
  if (line.includes('✓') || /\bok\b/.test(line.toLowerCase())) return 'log-line-ok'
  if (line.includes('⚠') || /warn/.test(line.toLowerCase())) return 'log-line-warn'
  if (line.includes('✗') || /error/.test(line.toLowerCase())) return 'log-line-error'
  if (line.includes('STEP')) return 'log-line-step'
  return 'log-line-muted'
}

export function Logs() {
  const [lines, setLines]   = useState<string[]>([])
  const [count, setCount]   = useState(200)
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
    <div className="p-6 flex flex-col h-full min-h-0 max-w-5xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Logs</h1>
      <p className="text-[12px] text-muted mb-4">Research engine log — last {lines.length} lines</p>

      <div className="flex gap-2 mb-3 flex-wrap">
        {[200, 500, 2000].map(n => (
          <Button key={n} variant={count === n ? 'primary' : 'secondary'} size="sm" onClick={() => load(n)}>
            Last {n}
          </Button>
        ))}
        <Button variant="secondary" size="sm" onClick={() => load(count)} loading={loading}>Refresh</Button>
      </div>

      {lines.length === 0 ? (
        <div className="text-muted text-sm">Log file is empty or not found.</div>
      ) : (
        <div
          ref={boxRef}
          className="flex-1 min-h-0 overflow-y-auto bg-surface border border-border rounded-md p-3 scrollbar-thin"
          style={{ maxHeight: 'calc(100vh - 200px)' }}
        >
          {lines.map((line, i) => (
            <div key={i} className={`font-mono text-[11px] leading-[1.6] break-all py-px ${lineClass(line)}`}>
              {line || ' '}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
