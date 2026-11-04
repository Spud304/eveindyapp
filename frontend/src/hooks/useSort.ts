import { useState } from 'react'

export type SortDir = 'asc' | 'desc'
export type SortState<K extends string> = { key: K; dir: SortDir }

/** Column sorting for a client-side table: click the same column to reverse, another to switch. */
export function useSort<K extends string>(initial: SortState<K>, onChange?: (sort: SortState<K>) => void) {
  const [sort, setSortState] = useState<SortState<K>>(initial)
  const toggle = (key: K, defaultDir: SortDir = 'asc') => {
    const next: SortState<K> = sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: defaultDir }
    setSortState(next)
    onChange?.(next)
  }
  return { sort, toggle }
}

type Comparable = string | number | boolean | null | undefined

/** Sorts rows by `pick(row)` in the given direction; null sorts last either way, ties fall back to `tiebreak`. */
export function sortRows<T>(rows: T[], dir: SortDir, pick: (row: T) => Comparable, tiebreak?: (row: T) => Comparable): T[] {
  const cmp = (a: Comparable, b: Comparable) => {
    if (a == null && b == null) return 0
    if (a == null) return 1
    if (b == null) return -1
    if (typeof a === 'string' && typeof b === 'string') return a.localeCompare(b)
    return a < b ? -1 : a > b ? 1 : 0
  }
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const primary = cmp(pick(a), pick(b))
    if (primary !== 0) return pick(a) == null || pick(b) == null ? primary : primary * sign
    return tiebreak ? cmp(tiebreak(a), tiebreak(b)) : 0
  })
}
