import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  className?: string
}

export function Modal({ open, onClose, title, children, className }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" />
      <div
        className={cn(
          'relative bg-surface border border-border2 rounded-lg shadow-2xl p-6 w-full max-w-md',
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-sm font-semibold text-text mb-4">{title}</div>
        {children}
      </div>
    </div>
  )
}
