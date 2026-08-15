import { cn } from '../../lib/cn'
import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size    = 'sm' | 'md' | 'xs'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

const variants: Record<Variant, string> = {
  primary:   'bg-accent text-bg hover:bg-accent-dim border border-accent font-semibold',
  secondary: 'bg-s2 text-text hover:bg-s3 border border-border2',
  ghost:     'bg-transparent text-muted hover:text-text hover:bg-s2 border border-transparent',
  danger:    'bg-transparent text-red hover:bg-red/10 border border-red/40 hover:border-red',
}
const sizes: Record<Size, string> = {
  xs: 'px-2 py-0.5 text-[10px] rounded',
  sm: 'px-2.5 py-1 text-[11px] rounded',
  md: 'px-4 py-1.5 text-[12px] rounded-md',
}

export function Button({ variant = 'secondary', size = 'md', loading, className, children, disabled, ...props }: Props) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap transition-colors',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className,
      )}
    >
      {loading && (
        <span className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
      )}
      {children}
    </button>
  )
}
