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

function renderBar(pct: number): string {
  const filled = Math.round(pct / 5)
  return '█'.repeat(filled) + '░'.repeat(20 - filled) + `  ${pct}%`
}

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

  // Elapsed timer
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

  if (loading) return <div className="p-6"><LoadingState /></div>
  if (!job) return <div className="p-6 text-muted text-sm">Job not found.</div>

  const isTerminal = ['done', 'failed', 'cancelled'].includes(job.status)

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center gap-3 mb-1">
        <h1 className="text-[18px] font-bold text-text">Job {job.job_id.slice(0, 16)}</h1>
        <StatusBadge status={job.status} />
      </div>
      <p className="text-[12px] text-muted mb-5">
        Started: {fmtTime(job.started_at)}
        {job.finished_at && ` · Finished: ${fmtTime(job.finished_at)}`}
        {job.elapsed_secs != null && ` · Duration: ${fmtElapsed(job.elapsed_secs)}`}
      </p>

      {/* Progress card */}
      <div className="bg-surface border border-border rounded-md p-5 mb-5">
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-[15px] font-bold text-text">{stageLabel || 'Pending'}</div>
            {stageSub && <div className="text-[11px] text-muted mt-0.5">{stageSub}</div>}
            {job.session_id && (
              <div className="text-[10px] text-muted mt-0.5 font-mono">Session: {job.session_id.slice(0, 16)}</div>
            )}
          </div>
          <div className="text-[36px] font-bold text-accent font-mono tabular-nums leading-none">
            {isTerminal && job.status !== 'done' ? '—' : `${pct}%`}
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-1 bg-s3 rounded-full overflow-hidden mb-2">
          <div
            className="h-full bg-accent rounded-full transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="font-mono text-[11px] text-accent tracking-wide">{renderBar(pct)}</div>

        {job.status === 'running' && (
          <div className="text-[10px] text-muted mt-2">Elapsed: {elapsed}s</div>
        )}
      </div>

      {/* Results */}
      {job.status === 'done' && (
        <div className="mb-5">
          <div className="grid grid-cols-4 gap-3 mb-4">
            {[
              ['Passed Gate',       job.n_passed],
              ['Tested',            job.n_tested],
              ['Rejected',          (job.n_tested ?? 0) - (job.n_passed ?? 0)],
              ['Duration',          fmtElapsed(job.elapsed_secs)],
            ].map(([label, val]) => (
              <div key={String(label)} className="bg-s2 border border-border rounded-md px-3 py-2.5">
                <div className="text-[10px] text-muted uppercase tracking-wider font-semibold">{label}</div>
                <div className="text-[18px] font-bold text-text font-mono mt-0.5">{val}</div>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Link to="/reports"    className="px-3 py-1.5 rounded-md bg-accent text-bg text-[12px] font-semibold hover:bg-accent-dim">View Reports</Link>
            <Link to="/strategies" className="px-3 py-1.5 rounded-md bg-s2 border border-border text-[12px] hover:bg-s3">Strategies</Link>
          </div>
        </div>
      )}
      {job.status === 'failed' && job.error && (
        <div className="mb-5 px-3 py-3 bg-red/10 border border-red/30 rounded-md">
          <div className="text-red text-[11px] font-semibold mb-1">Pipeline failed:</div>
          <pre className="text-[10px] text-red/80 whitespace-pre-wrap font-mono">{job.error.slice(0, 1000)}</pre>
        </div>
      )}

      {/* Log */}
      <h2 className="text-[13px] font-semibold text-text mb-2">Live Log</h2>
      <div
        ref={logRef}
        className="bg-surface border border-border rounded-md p-3 h-64 overflow-y-auto scrollbar-thin mb-4"
      >
        {logLines.length === 0 ? (
          <div className="text-muted text-[11px] font-mono">
            {job.status === 'running' ? '  Connecting to job stream…' : `  Job is ${job.status}`}
          </div>
        ) : logLines.map((l, i) => (
          <div key={i} className={`font-mono text-[11px] leading-[1.6] py-px ${l.cls}`}>{l.text}</div>
        ))}
      </div>

      {/* Controls */}
      <div className="flex gap-2 flex-wrap">
        <Link to="/jobs" className="px-3 py-1.5 rounded-md bg-s2 border border-border text-[12px] hover:bg-s3">← All Jobs</Link>
        {!isTerminal && <Button variant="danger" size="sm" onClick={cancelJob}>Stop Job</Button>}
        {isTerminal  && <Button variant="secondary" size="sm" onClick={restartJob}>Restart</Button>}
      </div>
    </div>
  )
}
