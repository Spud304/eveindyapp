/** Display helpers shared by features. Numbers are shown monospace and right-aligned by the caller. */

const int = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const dec2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function qty(n: number | null | undefined): string {
  return n == null ? '' : int.format(n)
}

/** ISK with the usual k / m / b suffixes; exact below 10k. */
export function isk(n: number | null | undefined): string {
  if (n == null) return '—'
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${dec2.format(n / 1e9)}b`
  if (abs >= 1e6) return `${dec2.format(n / 1e6)}m`
  if (abs >= 1e4) return `${dec2.format(n / 1e3)}k`
  return int.format(n)
}

export function iskExact(n: number | null | undefined): string {
  return n == null ? '' : `${int.format(n)} ISK`
}

/** 1d 4h 12m; seconds are dropped above an hour. */
export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return ''
  const s = Math.round(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h ${m}m`
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${s % 60}s`
  return `${s}s`
}

export function pct(n: number, digits = 2): string {
  return `${n.toFixed(digits)}%`
}

export function since(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 90) return 'just now'
  if (s < 5400) return `${Math.round(s / 60)} min ago`
  if (s < 129600) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export const ACTIVITIES = ['manufacturing', 'reaction', 'copying', 'invention'] as const

export const BUILD_CATEGORY_LABELS: Record<string, string> = {
  t2_items: 'T2 items (invented)',
  advanced_components: 'Advanced components',
  capital_components: 'Capital components',
  advanced_capital_components: 'Advanced capital components',
  fuel_blocks: 'Fuel blocks',
  reaction_intermediate: 'Reactions: intermediate',
  reaction_composite: 'Reactions: composite',
  reaction_hybrid: 'Reactions: hybrid',
  reaction_biochemical: 'Reactions: biochemical',
  reaction_molecular_forged: 'Reactions: molecular-forged',
}

export function securityTone(sec: number | null | undefined): 'ok' | 'warn' | 'bad' {
  if (sec == null || sec >= 0.45) return 'ok'
  return sec > 0 ? 'warn' : 'bad'
}
