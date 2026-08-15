import { cn } from '../../lib/cn'
import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
  title?: string
  action?: ReactNode
}

export function Panel({ children, className, title, action }: Props) {
  return (
    <div className={cn('bg-surface border border-border rounded-md', className)}>
      {(title || action) && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
          {title && <span className="text-[11px] font-semibold uppercase tracking-widest text-muted">{title}</span>}
          {action}
        </div>
      )}
      {children}
    </div>
  )
}
