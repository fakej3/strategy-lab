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
  primary:   'bg-accent text-white hover:bg-accent-dim border border-accent/0 font-semibold shadow-sm',
  secondary: 'bg-s2 text-text hover:bg-s3 border border-border2 hover:border-border3',
  ghost:     'bg-transparent text-muted hover:text-text hover:bg-s2 border border-transparent',
  danger:    'bg-transparent text-red hover:bg-red/10 border border-red/30 hover:border-red/60',
  icon:      'bg-transparent text-muted hover:text-text hover:bg-s2 border border-transparent p-0',
}

const sizes: Record<Size, string> = {
  xs: 'px-2 py-0.5 text-[10px] rounded gap-1',
  sm: 'px-2.5 py-1 text-[11px] rounded gap-1',
  md: 'px-3.5 py-1.5 text-[12px] rounded-md gap-1.5',
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
        <span className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin shrink-0" />
      )}
      {children}
    </button>
  )
}
