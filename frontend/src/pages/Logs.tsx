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
      <div className="page-header shrink-0">
        <div>
          <span className="page-title">Logs</span>
          <span className="ml-3 text-[10px] text-muted">Research engine log — {lines.length} lines</span>
        </div>
        <div className="flex gap-1.5">
          {[200, 500, 2000].map(n => (
            <Button key={n} variant={count === n ? 'primary' : 'secondary'} size="xs" onClick={() => load(n)}>
              {n}
            </Button>
          ))}
          <Button variant="secondary" size="xs" onClick={() => load(count)} loading={loading}>Refresh</Button>
        </div>
      </div>

      <div
        ref={boxRef}
        className="flex-1 overflow-y-auto scrollbar-thin bg-bg p-3"
      >
        {lines.length === 0 ? (
          <div className="text-muted text-[10px] font-mono">Log file is empty or not found.</div>
        ) : lines.map((line, i) => (
          <div key={i} className={`font-mono text-[10px] leading-[1.6] break-all py-px ${lineClass(line)}`}>
            {line || ' '}
          </div>
        ))}
      </div>
    </div>
  )
}
