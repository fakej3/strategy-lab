import { cn } from '../../lib/cn'
import type { ReactNode } from 'react'

interface Props {
  label: string
  value: string | number
  sub?: string
  icon?: ReactNode
  accent?: boolean
  positive?: boolean
  negative?: boolean
  pulse?: boolean
}

export function MetricTile({ label, value, sub, icon, accent, positive, negative, pulse }: Props) {
  return (
    <div className="bg-surface border border-border px-3 py-2 flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-widest text-muted select-none">{label}</span>
        {icon && <span className="text-muted opacity-60">{icon}</span>}
        {pulse && (
          <span className="ml-auto inline-block w-1.5 h-1.5 rounded-full bg-green animate-pulse" />
        )}
      </div>
      <div className={cn(
        'text-[16px] font-bold font-mono tabular-nums leading-none',
        accent   && 'text-accent',
        positive && 'text-green',
        negative && 'text-red',
        !accent && !positive && !negative && 'text-text',
      )}>
        {value}
      </div>
      {sub && <div className="text-[9px] text-muted">{sub}</div>}
    </div>
  )
}
