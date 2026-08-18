import { cn } from '../../lib/cn'
import type { ReactNode } from 'react'

interface Tab {
  id: string
  label: string
  count?: number
}

interface Props {
  tabs: Tab[]
  active: string
  onChange: (id: string) => void
  children?: ReactNode
  className?: string
}

export function Tabs({ tabs, active, onChange, children, className }: Props) {
  return (
    <div className={cn('flex items-center gap-0 border-b border-border', className)}>
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap',
            active === t.id
              ? 'border-accent text-accent'
              : 'border-transparent text-muted hover:text-text',
          )}
        >
          {t.label}
          {t.count != null && t.count > 0 && (
            <span className="ml-2 px-1.5 py-0.5 rounded-full text-xs bg-s3 text-muted tabular-nums">
              {t.count}
            </span>
          )}
        </button>
      ))}
      {children}
    </div>
  )
}
