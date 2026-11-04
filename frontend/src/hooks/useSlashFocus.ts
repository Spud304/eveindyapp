import { useEffect } from 'react'

const EDITABLE = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

/** "/" focuses the page's search box when nothing editable has focus, the way code hosts do. */
export function useSlashFocus(testId: string) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      const active = document.activeElement as HTMLElement | null
      if (active && (EDITABLE.has(active.tagName) || active.isContentEditable)) return
      const box = document.querySelector<HTMLInputElement>(`[data-testid="${testId}"]`)
      if (!box) return
      e.preventDefault()
      box.focus()
      box.select()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [testId])
}
