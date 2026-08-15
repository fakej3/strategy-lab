import { cn } from '../../lib/cn'

type Variant = 'pass' | 'warn' | 'fail' | 'muted' | 'blue' | 'accent' | 'pending'

const styles: Record<Variant, string> = {
  pass:    'text-green border border-green/30',
  warn:    'text-amber border border-amber/30',
  fail:    'text-red border border-red/30',
  muted:   'text-muted border border-border',
  blue:    'text-accent border border-accent/30',
  accent:  'text-accent border border-accent/30',
  pending: 'text-muted2 border border-border',
}

interface Props {
  variant?: Variant
  children: React.ReactNode
  className?: string
}

export function Badge({ variant = 'muted', children, className }: Props) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider whitespace-nowrap font-mono',
      styles[variant],
      className,
    )}>
      {children}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  if (s === 'done' || s === 'complete' || s === 'promising')
    return <Badge variant="pass">{status}</Badge>
  if (s === 'running')
    return (
      <Badge variant="warn">
        <span className="inline-block w-1 h-1 rounded-full bg-amber animate-pulse" />
        {status}
      </Badge>
    )
  if (s === 'failed' || s === 'fail' || s === 'reject')
    return <Badge variant="fail">{status}</Badge>
  if (s === 'needs improvement' || s === 'needs_improvement')
    return <Badge variant="warn">Needs Imp.</Badge>
  if (s === 'pending')
    return <Badge variant="pending">{status}</Badge>
  return <Badge variant="muted">{status}</Badge>
}
