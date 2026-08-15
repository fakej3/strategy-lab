import { useEffect, useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
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
        symbols:         fd.get('symbols'),
        intervals:       fd.get('intervals'),
        start_date:      fd.get('start_date'),
        end_date:        fd.get('end_date'),
        starting_capital:fd.get('starting_capital'),
        run_walk_forward:fd.has('run_walk_forward'),
        run_monte_carlo: fd.has('run_monte_carlo'),
        run_robustness:  fd.has('run_robustness'),
        fast_mode:       fd.has('fast_mode'),
      },
    }
    await schedulerApi.create(body)
    ;(e.target as HTMLFormElement).reset()
    load()
  }

  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-[18px] font-bold text-text mb-0.5">Research Scheduler</h1>
      <p className="text-[12px] text-muted mb-5">Automate research runs on a recurring schedule</p>

      {loading && <LoadingState />}

      {!loading && schedules.length === 0 && <EmptyState message="No schedules configured." />}

      {!loading && schedules.length > 0 && (
        <>
          <h2 className="text-[13px] font-semibold text-text mb-3">Active Schedules</h2>
          <div className="bg-surface border border-border rounded-md overflow-x-auto mb-6">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  {['Name', 'Frequency', 'Time (UTC)', 'Status', 'Last Run', ''].map(h => (
                    <th key={h} className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-wider text-muted">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {schedules.map(s => (
                  <tr key={s.id} className="border-b border-border last:border-0 hover:bg-s2">
                    <td className="px-3 py-2 font-semibold">{s.name}</td>
                    <td className="px-3 py-2 text-muted capitalize">{s.frequency}</td>
                    <td className="px-3 py-2 font-mono">
                      {String(s.hour).padStart(2,'0')}:{String(s.minute).padStart(2,'0')} UTC
                      {s.frequency === 'weekly'  && ` (${DAYS[s.day_of_week ?? 0]})`}
                      {s.frequency === 'monthly' && ` (day ${s.day_of_month})`}
                    </td>
                    <td className="px-3 py-2">
                      {s.enabled ? <Badge variant="pass">Enabled</Badge> : <Badge variant="muted">Disabled</Badge>}
                    </td>
                    <td className="px-3 py-2 text-muted">{s.last_run ? s.last_run.slice(0, 16) : '—'}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1.5">
                        <Button size="xs" variant="secondary" onClick={() => runNow(s.id)}>Run Now</Button>
                        <Button size="xs" variant="secondary" onClick={() => toggle(s.id)}>
                          {s.enabled ? 'Disable' : 'Enable'}
                        </Button>
                        <Button size="xs" variant="danger" onClick={() => del(s.id, s.name)}>Delete</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!loading && (
        <>
          <h2 className="text-[13px] font-semibold text-text mb-3">Create New Schedule</h2>
          <form onSubmit={create} className="flex flex-col gap-4">
            <section className="bg-surface border border-border rounded-md p-4">
              <div className="grid grid-cols-2 gap-3 mb-3">
                <Field label="Schedule Name" name="name" placeholder="Nightly BTC Research" required />
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Frequency</label>
                  <select name="frequency" value={freq} onChange={e => setFreq(e.target.value)}
                    className="bg-bg border border-border rounded px-2.5 py-1.5 text-[12px] text-text focus:outline-none focus:border-accent">
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                  </select>
                </div>
                <Field label="Hour (UTC)" name="hour" type="number" min="0" max="23" defaultValue="2" />
                <Field label="Minute" name="minute" type="number" min="0" max="59" defaultValue="0" />
                {freq === 'weekly' && (
                  <div className="flex flex-col gap-1">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">Day of Week</label>
                    <select name="day_of_week" className="bg-bg border border-border rounded px-2.5 py-1.5 text-[12px] text-text focus:outline-none focus:border-accent">
                      {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                    </select>
                  </div>
                )}
                {freq === 'monthly' && (
                  <Field label="Day of Month" name="day_of_month" type="number" min="1" max="28" defaultValue="1" />
                )}
              </div>
            </section>

            <section className="bg-surface border border-border rounded-md p-4">
              <div className="text-[10px] font-semibold uppercase tracking-widest text-muted mb-3">Research Configuration</div>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <Field label="Symbols"   name="symbols"   defaultValue="BTCUSDT" />
                <Field label="Intervals" name="intervals" defaultValue="1h" />
                <Field label="Start Date" name="start_date" type="date" defaultValue="2024-01-01" />
                <Field label="End Date"   name="end_date"   type="date" defaultValue={today} />
                <Field label="Starting Capital" name="starting_capital" type="number" defaultValue="100000" />
              </div>
              <div className="flex gap-4 flex-wrap">
                {[
                  { name: 'run_walk_forward', label: 'Walk-Forward' },
                  { name: 'run_monte_carlo',  label: 'Monte Carlo' },
                  { name: 'run_robustness',   label: 'Robustness' },
                  { name: 'fast_mode',        label: 'Fast Mode' },
                ].map(({ name, label }) => (
                  <label key={name} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" name={name} defaultChecked={name !== 'fast_mode'} className="accent-accent" />
                    <span className="text-[12px] text-text">{label}</span>
                  </label>
                ))}
              </div>
            </section>

            <Button type="submit" variant="primary" size="md">Create Schedule</Button>
          </form>
        </>
      )}
    </div>
  )
}

function Field({ label, name, type = 'text', defaultValue, placeholder, hint, min, max, required }: {
  label: string; name: string; type?: string; defaultValue?: string; placeholder?: string; hint?: string; min?: string; max?: string; required?: boolean
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</label>
      <input
        type={type} name={name} defaultValue={defaultValue} placeholder={placeholder}
        min={min} max={max} required={required}
        className="bg-bg border border-border rounded px-2.5 py-1.5 text-[12px] text-text placeholder:text-muted2 focus:outline-none focus:border-accent"
      />
      {hint && <div className="text-[10px] text-muted2">{hint}</div>}
    </div>
  )
}
