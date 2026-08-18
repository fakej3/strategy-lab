import { useEffect, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Calendar, Play, Pause, Trash2, Zap } from 'lucide-react'
import { schedulerApi } from '../api/scheduler'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { EmptyState, LoadingState } from '../components/ui/EmptyState'
import type { Schedule } from '../types'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export function Scheduler() {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setL]           = useState(true)
  const [freq, setFreq]           = useState<string>('daily')
  const navigate                  = useNavigate()

  const load = () => schedulerApi.list().then(setSchedules).finally(() => setL(false))
  useEffect(() => { load() }, [])

  async function toggle(id: string) {
    await schedulerApi.toggle(id)
    load()
  }

  async function del(id: string, name: string) {
    if (!confirm(`Delete schedule "${name}"?`)) return
    await schedulerApi.delete(id)
    load()
  }

  async function runNow(id: string) {
    const { job_id } = await schedulerApi.runNow(id)
    navigate(`/jobs/${job_id}`)
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
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
    await schedulerApi.create(body)
    ;(e.target as HTMLFormElement).reset()
    setFreq('daily')
    load()
  }

  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="flex flex-col h-full">
      <div className="page-header">
        <span className="page-title">Scheduler</span>
        {!loading && schedules.length > 0 && (
          <span className="text-xs text-muted">{schedules.length} schedule{schedules.length !== 1 ? 's' : ''}</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading && <LoadingState />}

        {!loading && schedules.length === 0 && (
          <div className="p-6 border-b border-border">
            <EmptyState
              message="No schedules configured."
              sub="Automate research runs on a recurring schedule."
            />
          </div>
        )}

        {!loading && schedules.length > 0 && (
          <div className="p-4 flex flex-col gap-2 border-b border-border">
            {schedules.map(s => (
              <div
                key={s.id}
                className="flex items-center gap-4 px-4 py-3.5 bg-surface border border-border rounded-lg"
              >
                <div className="w-8 h-8 rounded-lg bg-s3 flex items-center justify-center shrink-0">
                  <Calendar size={14} className="text-muted" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-text">{s.name}</div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-muted capitalize">{s.frequency}</span>
                    <span className="font-mono text-xs text-muted">
                      {String(s.hour).padStart(2,'0')}:{String(s.minute).padStart(2,'0')} UTC
                      {s.frequency === 'weekly'  && ` · ${DAYS[s.day_of_week ?? 0]}`}
                      {s.frequency === 'monthly' && ` · day ${s.day_of_month}`}
                    </span>
                    {s.last_run && (
                      <span className="text-xs text-muted2 font-mono">last {s.last_run.slice(0, 16)}</span>
                    )}
                  </div>
                </div>

                <div className="shrink-0">
                  {s.enabled
                    ? <Badge variant="pass">Enabled</Badge>
                    : <Badge variant="muted">Disabled</Badge>}
                </div>

                <div className="flex items-center gap-1 shrink-0 pl-2 border-l border-border">
                  <button
                    onClick={() => runNow(s.id)}
                    className="p-1.5 text-muted hover:text-accent rounded transition-colors"
                    title="Run now"
                  >
                    <Zap size={14} />
                  </button>
                  <button
                    onClick={() => toggle(s.id)}
                    className="p-1.5 text-muted hover:text-text rounded transition-colors"
                    title={s.enabled ? 'Disable' : 'Enable'}
                  >
                    {s.enabled ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                  <button
                    onClick={() => del(s.id, s.name)}
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

        {!loading && (
          <div className="p-4 max-w-2xl">
            <div className="flex items-center px-4 py-2.5 border-b border-border bg-surface rounded-t-lg">
              <span className="section-label">New Schedule</span>
            </div>
            <form onSubmit={create} className="bg-surface border border-border border-t-0 rounded-b-lg">
              <div className="p-4 border-b border-border">
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <Field label="Schedule Name" name="name" placeholder="Nightly Research" required />
                  <div className="flex flex-col gap-1.5">
                    <label className="field-label">Frequency</label>
                    <select name="frequency" value={freq} onChange={e => setFreq(e.target.value)} className="field-select">
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                      <option value="monthly">Monthly</option>
                    </select>
                  </div>
                  <Field label="Hour (UTC)" name="hour"   type="number" min="0" max="23" defaultValue="2" />
                  <Field label="Minute"     name="minute" type="number" min="0" max="59" defaultValue="0" />
                  {freq === 'weekly' && (
                    <div className="flex flex-col gap-1.5">
                      <label className="field-label">Day of Week</label>
                      <select name="day_of_week" className="field-select">
                        {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                      </select>
                    </div>
                  )}
                  {freq === 'monthly' && (
                    <Field label="Day of Month" name="day_of_month" type="number" min="1" max="28" defaultValue="1" />
                  )}
                </div>
              </div>

              <div className="p-4 border-b border-border">
                <div className="text-xs font-semibold text-muted mb-3">Research Config</div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <Field label="Symbols"         name="symbols"          defaultValue="BTCUSDT" />
                  <Field label="Intervals"        name="intervals"        defaultValue="1h" />
                  <Field label="Start Date"       name="start_date"       type="date" defaultValue="2024-01-01" />
                  <Field label="End Date"         name="end_date"         type="date" defaultValue={today} />
                  <Field label="Starting Capital" name="starting_capital" type="number" defaultValue="100000" />
                </div>
                <div className="flex flex-wrap gap-5">
                  {[
                    { name: 'run_walk_forward', label: 'Walk-Forward',  def: true },
                    { name: 'run_monte_carlo',  label: 'Monte Carlo',   def: true },
                    { name: 'run_robustness',   label: 'Robustness',    def: false },
                    { name: 'fast_mode',        label: 'Fast Mode',     def: false },
                  ].map(({ name, label, def }) => (
                    <label key={name} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        name={name}
                        defaultChecked={def}
                        className="w-3.5 h-3.5 accent-amber shrink-0"
                      />
                      <span className="text-sm text-text">{label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="p-4">
                <Button type="submit" variant="primary" size="sm">Create Schedule</Button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, placeholder, min, max, required }: {
  label: string; name: string; type?: string; defaultValue?: string; placeholder?: string; min?: string; max?: string; required?: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="field-label">{label}</label>
      <input
        type={type} name={name} defaultValue={defaultValue} placeholder={placeholder}
        min={min} max={max} required={required}
        className="field-input"
      />
    </div>
  )
}
