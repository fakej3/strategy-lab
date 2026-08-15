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
    <div className="bg-surface border border-border rounded-md px-4 py-3 flex flex-col gap-1.5 relative overflow-hidden">
      {/* Subtle top-edge highlight for positive/accent cards */}
      {(accent || positive) && (
        <div className={cn(
          'absolute top-0 inset-x-0 h-[2px] rounded-t-md',
          accent   && 'bg-accent',
          positive && 'bg-green',
        )} />
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted select-none">{label}</span>
        {icon && <span className="text-muted">{icon}</span>}
        {pulse && (
          <span className="inline-flex items-center gap-1 text-[9px] text-green font-medium">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-green animate-pulse" />
            live
          </span>
        )}
      </div>
      <div className={cn(
        'text-[22px] font-bold font-mono tabular-nums leading-none tracking-tight',
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
