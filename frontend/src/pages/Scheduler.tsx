import { useEffect, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Calendar, Trash2, Zap, Plus, ChevronDown, Clock } from 'lucide-react'
import { schedulerApi } from '../api/scheduler'
import { cn } from '../lib/cn'
import type { Schedule } from '../types'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function fmtNextRun(s: Schedule): string {
  const now = new Date()
  const next = new Date(now)
  next.setUTCHours(s.hour, s.minute, 0, 0)

  if (s.frequency === 'daily') {
    if (next <= now) next.setUTCDate(next.getUTCDate() + 1)
  } else if (s.frequency === 'weekly') {
    const dow = s.day_of_week ?? 1
    const diff = ((dow - now.getUTCDay()) + 7) % 7
    next.setUTCDate(next.getUTCDate() + diff)
    if (diff === 0 && next <= now) next.setUTCDate(next.getUTCDate() + 7)
  } else if (s.frequency === 'monthly') {
    next.setUTCDate(s.day_of_month ?? 1)
    if (next <= now) next.setUTCMonth(next.getUTCMonth() + 1)
  }

  const diffMs = next.getTime() - now.getTime()
  const diffH  = Math.round(diffMs / 3600000)
  if (diffH < 1) return 'in < 1h'
  if (diffH < 24) return `in ${diffH}h`
  const diffD = Math.floor(diffH / 24)
  return `in ${diffD}d`
}

export function Scheduler() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setL]           = useState(true)
  const [showForm, setShowForm]   = useState(false)
  const [freq, setFreq]           = useState<string>('daily')
  const [saving, setSaving]       = useState(false)
  const navigate                  = useNavigate()

  const load = () => schedulerApi.list().then(s => { setSchedules(s); setShowForm(s.length === 0) }).finally(() => setL(false))
  useEffect(() => { load() }, [])

  async function toggle(id: string) {
    await schedulerApi.toggle(id)
    load()
  }

  async function del(id: string, name: string) {
    if (!confirm(`Delete "${name}"?`)) return
    await schedulerApi.delete(id)
    load()
  }

  async function runNow(id: string) {
    const { job_id } = await schedulerApi.runNow(id)
    navigate(`/jobs/${job_id}`)
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setSaving(true)
    const fd = new FormData(e.currentTarget)
    const body = {
      name:         String(fd.get('name') ?? 'Scheduled Research'),
      frequency:    (String(fd.get('frequency') ?? 'daily')) as 'daily' | 'weekly' | 'monthly',
      hour:         Number(fd.get('hour') ?? 2),
      minute:       Number(fd.get('minute') ?? 0),
      day_of_week:  Number(fd.get('day_of_week') ?? 1),
      day_of_month: Number(fd.get('day_of_month') ?? 1),
      config: {
        symbols:          fd.get('symbols'),
        intervals:        fd.get('intervals'),
        start_date:       fd.get('start_date'),
        end_date:         fd.get('end_date'),
        starting_capital: fd.get('starting_capital'),
        run_walk_forward: fd.has('run_walk_forward'),
        run_monte_carlo:  fd.has('run_monte_carlo'),
        run_robustness:   fd.has('run_robustness'),
        fast_mode:        fd.has('fast_mode'),
      },
    }
    try {
      await schedulerApi.create(body)
      ;(e.target as HTMLFormElement).reset()
      setFreq('daily')
      setShowForm(false)
      load()
    } finally {
      setSaving(false)
    }
  }

  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-5 h-11 border-b border-border bg-surface shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-text">Scheduler</span>
          {!loading && schedules.length > 0 && (
            <span className="text-xs text-muted">{schedules.length} schedule{schedules.length !== 1 ? 's' : ''}</span>
          )}
        </div>
        <button
          onClick={() => setShowForm(f => !f)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-accent text-bg rounded-md hover:bg-accent-dim transition-colors"
        >
          <Plus size={12} />
          New Schedule
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-muted text-sm">
            <span className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin" />
            Loading…
          </div>
        ) : (
          <div className="p-5 flex flex-col gap-4">

            {/* Existing schedules */}
            {schedules.length > 0 && (
              <div className="flex flex-col gap-2">
                {schedules.map(s => (
                  <ScheduleCard key={s.id} schedule={s} onToggle={toggle} onDelete={del} onRunNow={runNow} />
                ))}
              </div>
            )}

            {/* Empty state */}
            {schedules.length === 0 && !showForm && (
              <div className="flex items-start gap-5 p-5 bg-surface border border-border rounded-xl">
                <div className="w-9 h-9 rounded-lg bg-s3 border border-border flex items-center justify-center shrink-0">
                  <Calendar size={15} className="text-muted2" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-text mb-1">No automation configured</div>
                  <div className="text-xs text-muted leading-relaxed mb-4 max-w-sm">
                    Schedule recurring research runs. EdgeLab will backtest your strategy automatically and store results for review.
                  </div>
                  <button
                    onClick={() => setShowForm(true)}
                    className="flex items-center gap-1.5 px-4 py-2 bg-accent text-bg text-xs font-semibold rounded-md hover:bg-accent-dim transition-colors"
                  >
                    <Plus size={12} />
                    Create First Schedule
                  </button>
                </div>
              </div>
            )}

            {/* New schedule form */}
            {showForm && (
              <div className="bg-surface border border-accent/20 rounded-xl overflow-hidden max-w-3xl">
                <button
                  onClick={() => setShowForm(false)}
                  className="w-full flex items-center justify-between px-5 py-3 border-b border-border hover:bg-s2 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Plus size={13} className="text-accent" />
                    <span className="text-sm font-semibold text-text">New Schedule</span>
                  </div>
                  <ChevronDown size={14} className={cn('text-muted transition-transform', showForm && 'rotate-180')} />
                </button>

                <form onSubmit={create} className="p-5 flex flex-col gap-5">
                  {/* Row 1: name + frequency */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="field-label block mb-1.5">Name</label>
                      <input name="name" type="text" placeholder="Nightly Research" required className="field-input" />
                    </div>
                    <div>
                      <label className="field-label block mb-1.5">Frequency</label>
                      <select name="frequency" value={freq} onChange={e => setFreq(e.target.value)} className="field-select w-full">
                        <option value="daily">Daily</option>
                        <option value="weekly">Weekly</option>
                        <option value="monthly">Monthly</option>
                      </select>
                    </div>
                  </div>

                  {/* Row 2: time + day */}
                  <div className="grid grid-cols-4 gap-3">
                    <div>
                      <label className="field-label block mb-1.5">Hour (UTC)</label>
                      <input name="hour" type="number" min="0" max="23" defaultValue="2" className="field-input" />
                    </div>
                    <div>
                      <label className="field-label block mb-1.5">Minute</label>
                      <input name="minute" type="number" min="0" max="59" defaultValue="0" className="field-input" />
                    </div>
                    {freq === 'weekly' && (
                      <div className="col-span-2">
                        <label className="field-label block mb-1.5">Day</label>
                        <select name="day_of_week" className="field-select w-full">
                          {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                        </select>
                      </div>
                    )}
                    {freq === 'monthly' && (
                      <div className="col-span-2">
                        <label className="field-label block mb-1.5">Day of month</label>
                        <input name="day_of_month" type="number" min="1" max="28" defaultValue="1" className="field-input" />
                      </div>
                    )}
                  </div>

                  {/* Divider */}
                  <div className="border-t border-border pt-5">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted2 mb-4">Research Configuration</div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="field-label block mb-1.5">Symbols</label>
                        <input name="symbols" type="text" defaultValue="BTCUSDT" placeholder="BTCUSDT, ETHUSDT" className="field-input font-mono" />
                      </div>
                      <div>
                        <label className="field-label block mb-1.5">Intervals</label>
                        <input name="intervals" type="text" defaultValue="1h" placeholder="1h, 4h" className="field-input font-mono" />
                      </div>
                      <div>
                        <label className="field-label block mb-1.5">Lookback Days</label>
                        <input name="lookback_days" type="number" defaultValue="365" min="7" placeholder="e.g. 365" className="field-input font-mono"
                          title="Number of calendar days from today to look back. Overrides Start Date when set." />
                      </div>
                      <div>
                        <label className="field-label block mb-1.5">Start Date <span className="text-muted2 text-xs">(ignored when Lookback Days set)</span></label>
                        <input name="start_date" type="date" defaultValue="" className="field-input" />
                      </div>
                      <div>
                        <label className="field-label block mb-1.5">End Date</label>
                        <input name="end_date" type="date" defaultValue={today} className="field-input" />
                      </div>
                      <div>
                        <label className="field-label block mb-1.5">Starting Capital</label>
                        <input name="starting_capital" type="number" defaultValue="100000" className="field-input font-mono" />
                      </div>
                    </div>

                    {/* Analysis toggles */}
                    <div className="flex flex-wrap gap-4 mt-4">
                      {[
                        { name: 'run_walk_forward', label: 'Walk-Forward',  def: true },
                        { name: 'run_monte_carlo',  label: 'Monte Carlo',   def: true },
                        { name: 'run_robustness',   label: 'Robustness',    def: false },
                        { name: 'fast_mode',        label: 'Fast Mode',     def: false },
                      ].map(({ name, label, def }) => (
                        <label key={name} className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" name={name} defaultChecked={def} className="w-3.5 h-3.5 accent-amber" />
                          <span className="text-xs text-text">{label}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      type="submit"
                      disabled={saving}
                      className="flex items-center gap-2 px-5 py-2.5 bg-accent text-bg text-sm font-bold rounded-lg hover:bg-accent-dim transition-colors disabled:opacity-50"
                    >
                      {saving && <span className="w-3.5 h-3.5 border-2 border-bg/40 border-t-bg rounded-full animate-spin" />}
                      {saving ? 'Saving…' : 'Create Schedule'}
                    </button>
                    {schedules.length > 0 && (
                      <button type="button" onClick={() => setShowForm(false)} className="text-xs text-muted hover:text-text transition-colors">
                        Cancel
                      </button>
                    )}
                  </div>
                </form>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function ScheduleCard({
  schedule: s, onToggle, onDelete, onRunNow,
}: {
  schedule: Schedule
  onToggle: (id: string) => void
  onDelete: (id: string, name: string) => void
  onRunNow: (id: string) => void
}) {
  const nextRun = s.enabled ? fmtNextRun(s) : null

  return (
    <div className={cn(
      'flex items-center gap-4 px-5 py-4 bg-surface border rounded-xl transition-colors',
      s.enabled ? 'border-border hover:border-border2' : 'border-border opacity-60',
    )}>
      {/* Status toggle */}
      <button
        onClick={() => onToggle(s.id)}
        title={s.enabled ? 'Disable' : 'Enable'}
        className={cn(
          'w-10 h-5.5 rounded-full border flex items-center px-0.5 transition-all shrink-0',
          s.enabled ? 'bg-green/20 border-green/30' : 'bg-s3 border-border',
        )}
        style={{ height: '22px', width: '38px' }}
      >
        <div className={cn(
          'w-4 h-4 rounded-full shadow transition-all',
          s.enabled ? 'bg-green translate-x-4' : 'bg-muted2 translate-x-0',
        )} />
      </button>

      {/* Icon */}
      <div className={cn(
        'w-9 h-9 rounded-lg flex items-center justify-center shrink-0',
        s.enabled ? 'bg-accent/10' : 'bg-s3',
      )}>
        <Calendar size={15} className={s.enabled ? 'text-accent' : 'text-muted2'} />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-text">{s.name}</div>
        <div className="flex items-center gap-3 mt-0.5 flex-wrap">
          <span className="text-xs text-muted capitalize">{s.frequency}</span>
          <span className="font-mono text-xs text-muted2">
            {String(s.hour).padStart(2,'0')}:{String(s.minute).padStart(2,'0')} UTC
            {s.frequency === 'weekly'  && ` · ${DAYS[s.day_of_week ?? 0]}`}
            {s.frequency === 'monthly' && ` · day ${s.day_of_month}`}
          </span>
          {s.last_run && (
            <span className="text-xs text-muted2 font-mono">last {s.last_run.slice(0,16).replace('T',' ')}</span>
          )}
        </div>
      </div>

      {/* Next run */}
      {nextRun && (
        <div className="flex items-center gap-1.5 text-xs text-muted shrink-0">
          <Clock size={11} />
          {nextRun}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-0.5 shrink-0">
        <button
          onClick={() => onRunNow(s.id)}
          className="p-2 text-muted hover:text-accent hover:bg-accent-bg rounded-lg transition-colors"
          title="Run now"
        >
          <Zap size={13} />
        </button>
        <button
          onClick={() => onDelete(s.id, s.name)}
          className="p-2 text-muted hover:text-red hover:bg-red/8 rounded-lg transition-colors"
          title="Delete"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  )
}
