export function fmt(
  v: number | null | undefined,
  decimals = 4,
  pct = false,
): string {
  if (v == null || isNaN(v)) return '—'
  if (pct) return `${(v * 100).toFixed(2)}%`
  return v.toFixed(decimals)
}

export function fmtSign(v: number | null | undefined, decimals = 2): string {
  if (v == null || isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(decimals)}`
}

export function fmtPct(v: number | null | undefined, decimals = 2): string {
  if (v == null || isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(decimals)}%`
}

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '—'
  if (v >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (v >= 1)    return v.toFixed(4)
  return v.toFixed(6)
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.slice(0, 19).replace('T', ' ')
}

export function fmtElapsed(secs: number | null | undefined): string {
  if (secs == null) return '—'
  if (secs < 60) return `${secs.toFixed(1)}s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  return `${m}m ${s}s`
}

export function fmtChange(v: number): string {
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

export function pnlClass(v: number | null | undefined): string {
  if (v == null) return 'text-muted'
  if (v > 0) return 'text-green'
  if (v < 0) return 'text-red'
  return 'text-muted'
}
