import type { ReactNode } from 'react'

interface Props {
  message: string
  sub?: string
  action?: ReactNode
}

export function EmptyState({ message, sub, action }: Props) {
  return (
    <div className="flex flex-col items-center gap-3 py-20 text-center">
      <p className="text-base font-semibold text-text">{message}</p>
      {sub && <p className="text-sm text-muted max-w-xs">{sub}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3.5 bg-red/8 border border-red/20 rounded-lg">
      <span className="text-red text-sm font-medium shrink-0">Error</span>
      <span className="text-red/80 text-sm">{message}</span>
    </div>
  )
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-muted">
      <span className="inline-block w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  )
}
