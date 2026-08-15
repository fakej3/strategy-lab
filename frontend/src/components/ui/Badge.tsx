import { cn } from '../../lib/cn'

type Variant = 'pass' | 'warn' | 'fail' | 'muted' | 'blue' | 'accent'

const styles: Record<Variant, string> = {
  pass:   'bg-green/15 text-green border border-green/30',
  warn:   'bg-amber/15 text-amber border border-amber/30',
  fail:   'bg-red/15 text-red border border-red/30',
  muted:  'bg-s2 text-muted border border-border',
  blue:   'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  accent: 'bg-accent/15 text-accent border border-accent/30',
}

interface Props {
  variant?: Variant
  children: React.ReactNode
  className?: string
}

export function Badge({ variant = 'muted', children, className }: Props) {
  return (
    <span className={cn(
      'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide',
      styles[variant],
      className,
    )}>
      {children}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  if (s === 'complete' || s === 'done' || s === 'promising')       return <Badge variant="pass">{status}</Badge>
  if (s === 'running')                                             return <Badge variant="warn">{status}</Badge>
  if (s === 'failed' || s === 'fail' || s === 'reject')           return <Badge variant="fail">{status}</Badge>
  if (s === 'needs improvement' || s === 'needs_improvement')     return <Badge variant="warn">Needs Imp.</Badge>
  return <Badge variant="muted">{status}</Badge>
}
