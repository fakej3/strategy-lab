import { useEffect, useRef, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { jobsApi } from '../api/jobs'
import { useJobWS } from '../hooks/useJobWS'
import { StatusBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { LoadingState } from '../components/ui/EmptyState'
import { fmtTime, fmtElapsed } from '../lib/format'
import type { Job, JobWsMessage } from '../types'

interface LogLine { cls: string; text: string }

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate  = useNavigate()
  const [job, setJob]       = useState<Job | null>(null)
  const [loading, setL]     = useState(true)
  const [pct, setPct]       = useState(0)
  const [stageLabel, setStageLabel] = useState('')
  const [stageSub,   setStageSub]   = useState('')
  const [logLines,   setLog]        = useState<LogLine[]>([])
  const [elapsed,    setElapsed]    = useState(0)
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!jobId) return
    jobsApi.get(jobId).then(j => {
      setJob(j)
      if (j.status === 'done') { setPct(100); setStageLabel('Complete') }
      else if (j.status === 'failed') setStageLabel('Failed')
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
      setStageLabel(p >= 100 ? 'Finalizing…' : `Step ${msg.n} — ${msg.label}`)
      addLog('log-line-step', `  STEP ${msg.n} · ${msg.label}`)
    } else if (msg.type === 'section') {
      setStageSub(msg.label)
      addLog('log-line-muted', msg.label)
    } else if (msg.type === 'ok')   addLog('log-line-ok',    `  ✓  ${msg.message}`)
    else if (msg.type === 'info')   addLog('log-line-muted', `  ·  ${msg.message}`)
    else if (msg.type === 'warn')   addLog('log-line-warn',  `  ⚠  ${msg.message}`)
    else if (msg.type === 'error')  addLog('log-line-error', `  ✗  ${msg.message}`)
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

  if (loading) return <div className="flex flex-col h-full"><div className="page-header shrink-0"><span className="page-title">Job Detail</span></div><div className="p-5"><LoadingState /></div></div>
  if (!job) return <div className="flex flex-col h-full"><div className="page-header shrink-0"><span className="page-title">Job Detail</span></div><div className="p-5 text-muted text-xs">Job not found.</div></div>

  const isTerminal = ['done', 'failed', 'cancelled'].includes(job.status)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="page-header shrink-0">
        <div className="flex items-center gap-3">
          <Link to="/jobs" className="text-[10px] text-muted hover:text-text">← Jobs</Link>
          <span className="text-muted2">/</span>
          <span className="page-title font-mono">{job.job_id.slice(0, 16)}</span>
          <StatusBadge status={job.status} />
        </div>
        <div className="flex gap-1.5">
          {!isTerminal && <Button variant="danger" size="xs" onClick={cancelJob}>Stop</Button>}
          {isTerminal  && <Button variant="secondary" size="xs" onClick={restartJob}>Restart</Button>}
        </div>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-5 px-5 py-2 border-b border-border bg-surface text-[10px] text-muted shrink-0">
        <span>Started: <span className="text-text font-mono">{fmtTime(job.started_at)}</span></span>
        {job.finished_at && <span>Finished: <span className="text-text font-mono">{fmtTime(job.finished_at)}</span></span>}
        {job.elapsed_secs != null && <span>Duration: <span className="text-text font-mono">{fmtElapsed(job.elapsed_secs)}</span></span>}
        {job.status === 'running' && <span>Elapsed: <span className="text-accent font-mono">{elapsed}s</span></span>}
        {job.session_id && <span className="ml-auto font-mono text-muted2">{job.session_id.slice(0, 16)}</span>}
      </div>

      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {/* Progress section */}
        <div className="px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-4 mb-2">
            <div className="flex-1">
              <div className="text-[13px] font-semibold text-text">{stageLabel || 'Pending'}</div>
              {stageSub && <div className="text-[10px] text-muted mt-0.5">{stageSub}</div>}
            </div>
            <div className="text-[22px] font-bold font-mono tabular-nums text-accent leading-none">
              {isTerminal && job.status !== 'done' ? '—' : `${pct}%`}
            </div>
          </div>
          <div className="h-0.5 bg-s3 overflow-hidden mb-1">
            <div
              className="h-full bg-accent transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>

        {/* Results row (done only) */}
        {job.status === 'done' && (
          <div className="flex items-center gap-0 border-b border-border shrink-0">
            {[
              ['Passed Gate', job.n_passed, 'text-green'],
              ['Tested',      job.n_tested, 'text-text'],
              ['Rejected',    (job.n_tested ?? 0) - (job.n_passed ?? 0), 'text-red'],
              ['Duration',    fmtElapsed(job.elapsed_secs), 'text-muted'],
            ].map(([label, val, cls]) => (
              <div key={String(label)} className="flex-1 px-5 py-2.5 border-r border-border last:border-0">
                <div className="text-[9px] font-semibold uppercase tracking-widest text-muted mb-1">{label}</div>
                <div className={`text-[18px] font-bold font-mono tabular-nums ${cls}`}>{val}</div>
              </div>
            ))}
            <div className="px-5 py-2.5 flex flex-col gap-1 justify-center">
              <Link to="/reports"    className="px-2.5 py-1 text-[10px] font-semibold bg-accent text-bg hover:bg-accent-dim transition-colors">Reports</Link>
              <Link to="/strategies" className="px-2.5 py-1 text-[10px] text-muted border border-border hover:border-border2 hover:text-text transition-colors">Strategies</Link>
            </div>
          </div>
        )}

        {/* Error block */}
        {job.status === 'failed' && job.error && (
          <div className="mx-5 mt-3 px-3 py-2.5 bg-red/8 border border-red/25 shrink-0">
            <div className="text-red text-[10px] font-semibold mb-1">Pipeline failed:</div>
            <pre className="text-[10px] text-red/70 whitespace-pre-wrap font-mono">{job.error.slice(0, 1000)}</pre>
          </div>
        )}

        {/* Log */}
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          <div className="flex items-center px-5 py-1.5 border-b border-border shrink-0 bg-surface">
            <span className="section-label">Live Log</span>
          </div>
          <div
            ref={logRef}
            className="flex-1 min-h-0 overflow-y-auto scrollbar-thin bg-bg p-3"
          >
            {logLines.length === 0 ? (
              <div className="text-muted text-[10px] font-mono">
                {job.status === 'running' ? '  Connecting to job stream…' : `  Job is ${job.status}`}
              </div>
            ) : logLines.map((l, i) => (
              <div key={i} className={`font-mono text-[10px] leading-[1.6] py-px ${l.cls}`}>{l.text}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
