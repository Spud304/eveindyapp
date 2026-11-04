import { useEffect, useState } from 'react'
import clsx from 'clsx'

/**
 * One-line confirmations after an action ("Plan saved"). A module-level store so anything can call
 * `notify`; mutations opt in through `meta: { toast }` and the query client's mutation cache calls it.
 */
export type Toast = { id: number; message: string; tone: 'ok' | 'bad' | 'muted' }

const LIFETIME_MS = 4000
const MAX_VISIBLE = 3

let nextId = 1
let toasts: Toast[] = []
const listeners = new Set<(items: Toast[]) => void>()

function publish() {
  for (const l of listeners) l(toasts)
}

export function notify(message: string, tone: Toast['tone'] = 'ok') {
  const toast = { id: nextId++, message, tone }
  toasts = [...toasts, toast].slice(-MAX_VISIBLE)
  publish()
  window.setTimeout(() => dismiss(toast.id), LIFETIME_MS)
}

export function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id)
  publish()
}

export function Toasts() {
  const [items, setItems] = useState<Toast[]>(toasts)
  useEffect(() => {
    listeners.add(setItems)
    return () => {
      listeners.delete(setItems)
    }
  }, [])
  if (!items.length) return null
  return (
    <div className="pointer-events-none fixed right-4 bottom-8 z-50 flex flex-col items-end gap-1" aria-live="polite">
      {items.map((t) => (
        <button
          type="button"
          key={t.id}
          onClick={() => dismiss(t.id)}
          data-testid="toast"
          data-tone={t.tone}
          className={clsx(
            'pointer-events-auto rounded border px-3 py-1.5 text-ui shadow',
            t.tone === 'ok' && 'border-ok/40 bg-panel text-fg',
            t.tone === 'bad' && 'border-bad/40 bg-panel text-bad',
            t.tone === 'muted' && 'border-line bg-panel text-muted',
          )}
        >
          {t.message}
        </button>
      ))}
    </div>
  )
}

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: { toast?: string }
  }
}
