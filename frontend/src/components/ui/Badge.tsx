import { cn } from '../../lib/cn'

type Variant = 'pass' | 'warn' | 'fail' | 'muted' | 'blue' | 'accent' | 'pending'

const styles: Record<Variant, string> = {
  pass:    'text-green bg-green/10',
  warn:    'text-amber bg-amber/10',
  fail:    'text-red bg-red/10',
  muted:   'text-muted bg-s3',
  blue:    'text-accent bg-accent-bg',
  accent:  'text-accent bg-accent-bg',
  pending: 'text-muted2 bg-s2',
}

interface Props {
  variant?: Variant
  children: React.ReactNode
  className?: string
}

export function Badge({ variant = 'muted', children, className }: Props) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-md whitespace-nowrap',
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
    return <Badge variant="warn">Needs work</Badge>
  if (s === 'pending')
    return <Badge variant="pending">{status}</Badge>
  return <Badge variant="muted">{status}</Badge>
}
