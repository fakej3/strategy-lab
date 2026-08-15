import type { ReactNode } from 'react'

interface Props {
  message: string
  action?: ReactNode
}

export function EmptyState({ message, action }: Props) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-muted">
      <span className="text-sm">{message}</span>
      {action}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 bg-red/10 border border-red/30 rounded-md text-red text-sm">
      <span>Error: {message}</span>
    </div>
  )
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-muted text-sm">
      <span className="inline-block w-4 h-4 border border-muted border-t-transparent rounded-full animate-spin" />
      {label}
    </div>
  )
}
