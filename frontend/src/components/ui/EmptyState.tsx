import type { ReactNode } from 'react'

interface Props {
  message: string
  sub?: string
  action?: ReactNode
}

export function EmptyState({ message, sub, action }: Props) {
  return (
    <div className="flex flex-col items-center gap-2 py-16 text-center">
      <p className="text-[13px] text-text font-medium">{message}</p>
      {sub && <p className="text-[11px] text-muted max-w-xs">{sub}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2.5 px-4 py-3 bg-red/10 border border-red/20 rounded-md">
      <span className="text-red text-[11px] font-medium">Error:</span>
      <span className="text-red text-[11px]">{message}</span>
    </div>
  )
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-muted">
      <span className="inline-block w-4 h-4 border border-muted/40 border-t-muted rounded-full animate-spin" />
      <span className="text-[12px]">{label}</span>
    </div>
  )
}
