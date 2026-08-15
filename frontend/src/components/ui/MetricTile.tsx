import { cn } from '../../lib/cn'

interface Props {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
  positive?: boolean
  negative?: boolean
}

export function MetricTile({ label, value, sub, accent, positive, negative }: Props) {
  return (
    <div className="bg-surface border border-border rounded-md px-4 py-3 flex flex-col gap-1">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-muted">{label}</div>
      <div className={cn(
        'text-xl font-bold font-mono tabular-nums leading-none',
        accent   && 'text-accent',
        positive && 'text-green',
        negative && 'text-red',
        !accent && !positive && !negative && 'text-text',
      )}>
        {value}
      </div>
      {sub && <div className="text-[10px] text-muted">{sub}</div>}
    </div>
  )
}
