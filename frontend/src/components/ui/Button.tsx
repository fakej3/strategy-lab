import { cn } from '../../lib/cn'
import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'icon'
type Size    = 'xs' | 'sm' | 'md'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

const variants: Record<Variant, string> = {
  primary:   'bg-accent text-bg hover:bg-accent-dim font-semibold shadow-sm',
  secondary: 'bg-s2 text-text hover:bg-s3 border border-border hover:border-border2',
  ghost:     'bg-transparent text-muted hover:text-text hover:bg-s2',
  danger:    'bg-transparent text-red hover:bg-red/10 border border-red/30 hover:border-red/60',
  icon:      'bg-transparent text-muted hover:text-text hover:bg-s2 p-0',
}

const sizes: Record<Size, string> = {
  xs: 'px-2.5 py-1 text-xs rounded gap-1',
  sm: 'px-3 py-1.5 text-sm rounded-md gap-1.5',
  md: 'px-4 py-2 text-base rounded-md gap-2',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading,
  className,
  children,
  disabled,
  ...props
}: Props) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center whitespace-nowrap transition-all duration-150',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/60',
        'disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none',
        variants[variant],
        variant !== 'icon' && sizes[size],
        className,
      )}
    >
      {loading && (
        <span className="inline-block w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin shrink-0" />
      )}
      {children}
    </button>
  )
}
