import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Search, X } from 'lucide-react'
import { logsApi } from '../api/logs'
import { cn } from '../lib/cn'

type Severity = 'all' | 'error' | 'warn' | 'ok' | 'info'

interface ParsedLine {
  raw:      string
  ts:       string
  body:     string
  severity: 'error' | 'warn' | 'ok' | 'info'
}

function parseLine(line: string): ParsedLine {
  const tsMatch = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/)
  const ts   = tsMatch ? tsMatch[1].slice(11) : ''
  const body = tsMatch ? line.slice(tsMatch[0].length).replace(/,\d+\s*/, ' ').trimStart() : line

  let severity: ParsedLine['severity'] = 'info'
  if (/✗|error|fail|blocked|exception/i.test(body)) severity = 'error'
  else if (/⚠|warn/i.test(body)) severity = 'warn'
  else if (/✓|complete|passed|success|ok\b/i.test(body) && !/fail/i.test(body)) severity = 'ok'

  return { raw: line, ts, body, severity }
}

const LINE_COUNTS = [200, 500, 2000]

const SEV_LABEL: Record<Severity, string> = {
  all:   'All',
  error: 'Errors',
  warn:  'Warnings',
  ok:    'Success',
  info:  'Info',
}

const SEV_COLOR: Record<Severity, string> = {
  all:   '',
  error: 'text-red',
  warn:  'text-amber',
  ok:    'text-green',
  info:  'text-muted',
}

export function Logs() {
  const [parsed,  setParsed]  = useState<ParsedLine[]>([])
  const [count,   setCount]   = useState(200)
  const [loading, setLoading] = useState(false)
  const [sev,     setSev]     = useState<Severity>('all')
  const [search,  setSearch]  = useState('')
  const boxRef = useRef<HTMLDivElement>(null)

  const load = (n: number) => {
    setLoading(true)
    logsApi.get(n)
      .then(d => {
        setParsed(d.lines.filter(l => l.trim()).map(parseLine))
        setCount(n)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(200) }, [])

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [parsed])

  const filtered = parsed.filter(l => {
    if (sev !== 'all' && l.severity !== sev) return false
    if (search && !l.raw.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const errorCount = parsed.filter(l => l.severity === 'error').length
  const warnCount  = parsed.filter(l => l.severity === 'warn').length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 h-11 border-b border-border bg-surface shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-text">Logs</span>
          <span className="text-xs text-muted">{parsed.length} lines</span>
          {errorCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-red px-2 py-0.5 bg-red/10 rounded-full">
              {errorCount} error{errorCount !== 1 ? 's' : ''}
            </span>
          )}
          {warnCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-amber px-2 py-0.5 bg-amber/10 rounded-full">
              {warnCount} warn{warnCount !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <div className="flex rounded-md overflow-hidden border border-border">
            {LINE_COUNTS.map(n => (
              <button
                key={n}
                onClick={() => load(n)}
                className={cn(
                  'px-3 py-1.5 text-xs font-mono transition-colors',
                  count === n ? 'bg-accent text-bg font-semibold' : 'bg-surface text-muted hover:text-text hover:bg-s2',
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

      {/* Filters */}
      <div className="flex items-center gap-3 px-5 py-2 border-b border-border bg-surface shrink-0">
        {/* Severity tabs */}
        <div className="flex items-center gap-0.5">
          {(['all', 'error', 'warn', 'ok', 'info'] as Severity[]).map(s => (
            <button
              key={s}
              onClick={() => setSev(s)}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                sev === s ? 'bg-s3 text-text' : 'text-muted hover:text-text hover:bg-s2',
                sev === s && s !== 'all' ? SEV_COLOR[s] : '',
              )}
            >
              {SEV_LABEL[s]}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="flex items-center gap-1.5 bg-s2 border border-border rounded-md px-2.5 py-1 flex-1 max-w-[280px]">
          <Search size={11} className="text-muted2 shrink-0" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter logs…"
            className="bg-transparent text-xs text-text placeholder:text-muted2 outline-none flex-1 min-w-0"
          />
          {search && (
            <button onClick={() => setSearch('')} className="text-muted2 hover:text-text transition-colors">
              <X size={11} />
            </button>
          )}
        </div>

        {filtered.length !== parsed.length && (
          <span className="text-xs text-muted2">{filtered.length} shown</span>
        )}
      </div>

      {/* Log content */}
      <div
        ref={boxRef}
        className="flex-1 overflow-y-auto scrollbar-thin bg-bg font-mono text-xs"
      >
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted text-sm">
            {parsed.length === 0 ? 'Log file is empty.' : 'No matching lines.'}
          </div>
        ) : (
          <table className="w-full">
            <tbody>
              {filtered.map((line, i) => (
                <tr key={i} className={cn(
                  'border-b border-border/30 hover:bg-s2/30 transition-colors',
                )}>
                  {line.ts && (
                    <td className="text-muted2 pr-3 pl-4 py-0.5 text-[11px] whitespace-nowrap w-[70px] align-top pt-1.5 select-none">
                      {line.ts}
                    </td>
                  )}
                  <td className={cn(
                    'py-0.5 pl-2 pr-4 leading-relaxed break-all align-top pt-1.5',
                    line.severity === 'error' ? 'text-red' : line.severity === 'warn' ? 'text-amber' : line.severity === 'ok' ? 'text-green' : 'text-muted',
                  )}
                  colSpan={line.ts ? 1 : 2}
                  >
                    {search
                      ? highlightSearch(line.body, search)
                      : line.body || ' '
                    }
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

function highlightSearch(text: string, search: string): React.ReactNode {
  if (!search) return text
  const idx = text.toLowerCase().indexOf(search.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-accent/30 text-text rounded-sm">{text.slice(idx, idx + search.length)}</mark>
      {text.slice(idx + search.length)}
    </>
  )
}
