import { cn } from '../../lib/cn'

type Variant = 'pass' | 'warn' | 'fail' | 'muted' | 'blue' | 'accent' | 'pending'

const styles: Record<Variant, string> = {
  pass:    'bg-green/10 text-green border border-green/20',
  warn:    'bg-amber/10 text-amber border border-amber/20',
  fail:    'bg-red/10 text-red border border-red/20',
  muted:   'bg-s2 text-muted border border-border',
  blue:    'bg-accent/10 text-accent border border-accent/20',
  accent:  'bg-accent/10 text-accent border border-accent/20',
  pending: 'bg-s3 text-muted2 border border-border2',
}

interface Props {
  variant?: Variant
  children: React.ReactNode
  className?: string
}

export function Badge({ variant = 'muted', children, className }: Props) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wide whitespace-nowrap',
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
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
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
