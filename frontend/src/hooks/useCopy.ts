import { useEffect, useRef, useState } from 'react'

/**
 * Copy to the clipboard and remember which item was copied for 1.5 s (for a "Copied" label).
 * When the browser refuses clipboard access the text is shown in a prompt to copy by hand.
 */
export function useCopy<K = true>() {
  const [copied, setCopied] = useState<K | null>(null)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const copy = async (text: string, key: K, what = 'text') => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(key)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(null), 1500)
    } catch {
      window.prompt(`Copy the ${what}:`, text)
    }
  }
  return { copied, copy }
}
