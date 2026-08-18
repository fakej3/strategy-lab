import { useEffect, useRef, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, CandlestickChart, BarChart2, RotateCcw } from 'lucide-react'
import { jobsApi } from '../api/jobs'
import { useJobWS } from '../hooks/useJobWS'
import { StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import { cn } from '../lib/cn'
import type { Job, JobWsMessage } from '../types'

interface LogLine { cls: string; text: string }

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate  = useNavigate()

  const [job,        setJob]       = useState<Job | null>(null)
  const [loading,    setL]         = useState(true)
  const [pct,        setPct]       = useState(0)
  const [stageLabel, setStageLabel] = useState('')
  const [stageSub,   setStageSub]   = useState('')
  const [logLines,   setLog]        = useState<LogLine[]>([])
  const [elapsed,    setElapsed]    = useState(0)
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!jobId) return
    jobsApi.get(jobId).then(j => {
      setJob(j)
      if (j.status === 'done')      { setPct(100); setStageLabel('Complete') }
      else if (j.status === 'failed')    setStageLabel('Failed')
      else if (j.status === 'cancelled') setStageLabel('Cancelled')
      else setStageLabel('Connecting…')
    }).finally(() => setL(false))
  }, [jobId])

  useEffect(() => {
    if (job?.status !== 'running') return
    const t = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [job?.status])

  function addLog(cls: string, text: string) {
    setLog(prev => {
      const next = [...prev, { cls, text }]
      return next.length > 500 ? next.slice(-500) : next
    })
    setTimeout(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
    }, 0)
  }

  function onWsMsg(msg: JobWsMessage) {
    if (msg.type === 'step') {
      const p = msg.pct ?? 0
      setPct(prev => Math.max(prev, p))
      setStageLabel(p >= 100 ? 'Finalizing…' : `${msg.label}`)
      addLog('log-line-step', `  ▸  ${msg.label}`)
    } else if (msg.type === 'section') {
      setStageSub(msg.label)
      addLog('log-line-muted', `  ${msg.label}`)
    } else if (msg.type === 'ok')    addLog('log-line-ok',    `  ✓  ${msg.message}`)
      else if (msg.type === 'info')  addLog('log-line-muted', `  ·  ${msg.message}`)
      else if (msg.type === 'warn')  addLog('log-line-warn',  `  ⚠  ${msg.message}`)
      else if (msg.type === 'error') addLog('log-line-error', `  ✗  ${msg.message}`)
      else if (msg.type === 'done') {
        setPct(100)
        setStageLabel(msg.success ? 'Complete' : (msg.cancelled ? 'Cancelled' : 'Failed'))
        setStageSub('')
        if (msg.success) addLog('log-line-ok', '  ✓  Research complete')
        else addLog('log-line-error', '  ✗  Pipeline failed')
        setJob(prev => prev ? {
          ...prev,
          status: msg.success ? 'done' : (msg.cancelled ? 'cancelled' : 'failed'),
          n_passed: msg.n_passed ?? prev.n_passed,
          n_tested: msg.n_tested ?? prev.n_tested,
          elapsed_secs: msg.elapsed_secs ?? prev.elapsed_secs,
          error: msg.error ?? prev.error,
        } : prev)
      }
  }

  useJobWS(jobId ?? '', onWsMsg, !!(job && (job.status === 'running' || job.status === 'pending')))

  async function cancelJob() {
    if (!jobId) return
    await jobsApi.cancel(jobId)
    setJob(prev => prev ? { ...prev, status: 'cancelled' } : prev)
  }

  async function restartJob() {
    if (!jobId) return
    const { job_id } = await jobsApi.restart(jobId)
    navigate(`/jobs/${job_id}`)
  }

  if (loading) return (
    <div className="flex flex-col h-full">
      <div className="page-header"><span className="page-title">Job</span></div>
      <LoadingState />
    </div>
  )
  if (!job) return (
    <div className="flex flex-col h-full">
      <div className="page-header"><span className="page-title">Job</span></div>
      <div className="p-6 text-muted text-sm">Job not found.</div>
    </div>
  )

  const isTerminal = ['done', 'failed', 'cancelled'].includes(job.status)

  // Build "Trade this" link from job config
  const cfg = job.config ?? {}
  const cfgSymbols    = cfg.symbols as string | string[] | undefined
  const cfgIntervals  = cfg.intervals as string | string[] | undefined
  const cfgStrategies = cfg.strategies as string[] | undefined
  const tradeSymbol   = Array.isArray(cfgSymbols)   ? cfgSymbols[0]   : cfgSymbols
  const tradeInterval = Array.isArray(cfgIntervals)  ? cfgIntervals[0] : cfgIntervals
  const tradeStrategy = cfgStrategies?.[0]
  const tradeParams = tradeSymbol && tradeInterval && tradeStrategy
    ? new URLSearchParams({ symbol: tradeSymbol, interval: tradeInterval, strategy: tradeStrategy }).toString()
    : null

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center gap-3">
          <Link to="/jobs" className="text-muted hover:text-text transition-colors flex items-center gap-1">
            <ArrowLeft size={14} />
            <span className="text-sm">Jobs</span>
          </Link>
          <span className="text-muted2">/</span>
          <span className="font-mono text-sm text-text">{job.job_id.slice(0, 16)}…</span>
          <StatusBadge status={job.status} />
        </div>
        <div className="flex gap-2">
          {!isTerminal && <Button variant="danger" size="sm" onClick={cancelJob}>Cancel</Button>}
          {isTerminal  && <Button variant="secondary" size="sm" onClick={restartJob}><RotateCcw size={13} /> Restart</Button>}
        </div>
      </div>

      {/* Meta strip */}
      <div className="flex items-center gap-5 px-6 py-2.5 border-b border-border bg-surface text-xs text-muted shrink-0">
        <span>Started <span className="text-text font-mono ml-1">{fmtTime(job.started_at)}</span></span>
        {job.finished_at && <span>Finished <span className="text-text font-mono ml-1">{fmtTime(job.finished_at)}</span></span>}
        {job.elapsed_secs != null && <span>Duration <span className="text-text font-mono ml-1">{fmtElapsed(job.elapsed_secs)}</span></span>}
        {job.status === 'running' && <span>Elapsed <span className="text-accent font-mono ml-1">{elapsed}s</span></span>}
      </div>

      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {/* Progress */}
        <div className="px-6 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-4 mb-3">
            <div className="flex-1">
              <div className="text-base font-semibold text-text">{stageLabel || 'Pending'}</div>
              {stageSub && <div className="text-sm text-muted mt-0.5">{stageSub}</div>}
            </div>
            <div className={cn(
              'text-3xl font-bold font-mono tabular-nums leading-none',
              isTerminal && job.status !== 'done' ? 'text-muted' : 'text-accent',
            )}>
              {isTerminal && job.status !== 'done' ? '—' : `${pct}%`}
            </div>
          </div>
          <div className="h-1 bg-s3 rounded-full overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full transition-all duration-500',
                job.status === 'failed' ? 'bg-red' :
                job.status === 'cancelled' ? 'bg-muted' : 'bg-accent',
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {/* Results row (done only) */}
        {job.status === 'done' && (
          <div className="grid grid-cols-5 border-b border-border shrink-0">
            {[
              { label: 'Passed Gate', val: job.n_passed,  cls: 'text-green' },
              { label: 'Tested',      val: job.n_tested,  cls: 'text-text' },
              { label: 'Rejected',    val: (job.n_tested ?? 0) - (job.n_passed ?? 0), cls: 'text-red' },
              { label: 'Duration',    val: fmtElapsed(job.elapsed_secs), cls: 'text-muted' },
            ].map(({ label, val, cls }) => (
              <div key={label} className="px-6 py-4 border-r border-border">
                <div className="text-xs text-muted mb-1.5">{label}</div>
                <div className={cn('text-3xl font-bold font-mono tabular-nums', cls)}>{val}</div>
              </div>
            ))}
            <div className="px-4 py-4 flex flex-col gap-2 justify-center">
              {tradeParams && (job.n_passed ?? 0) > 0 && (
                <Link
                  to={`/paper-trading?${tradeParams}`}
                  className="flex items-center gap-2 px-3 py-1.5 bg-green/10 text-green text-xs font-semibold rounded-md hover:bg-green/20 transition-colors"
                >
                  <CandlestickChart size={13} />
                  Trade this
                </Link>
              )}
              <Link
                to="/strategies"
                className="flex items-center gap-2 px-3 py-1.5 bg-s3 text-text text-xs font-medium rounded-md hover:bg-s2 transition-colors"
              >
                <BarChart2 size={13} />
                All strategies
              </Link>
            </div>
          </div>
        )}

        {/* Error block */}
        {job.status === 'failed' && job.error && (
          <div className="mx-6 mt-4 px-4 py-3 bg-red/8 border border-red/20 rounded-lg shrink-0">
            <div className="text-red text-sm font-semibold mb-2">Pipeline failed</div>
            <pre className="text-xs text-red/70 whitespace-pre-wrap font-mono">{job.error.slice(0, 1000)}</pre>
          </div>
        )}

        {/* Log */}
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          <div className="flex items-center px-6 py-2.5 border-b border-border shrink-0 bg-surface">
            <span className="section-label">Live Log</span>
          </div>
          <div
            ref={logRef}
            className="flex-1 min-h-0 overflow-y-auto scrollbar-thin bg-bg px-4 py-3"
          >
            {logLines.length === 0 ? (
              <div className="text-muted text-xs font-mono py-4">
                {job.status === 'running' ? '  Connecting to job stream…' : `  Job is ${job.status}`}
              </div>
            ) : logLines.map((l, i) => (
              <div key={i} className={cn('font-mono text-xs leading-relaxed py-px', l.cls)}>{l.text}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
