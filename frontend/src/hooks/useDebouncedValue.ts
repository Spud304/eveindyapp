import { useEffect, useState } from 'react'

/** `value` once it has stopped changing for `delay` ms; search boxes query with this, not every keystroke. */
export function useDebouncedValue<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const handle = window.setTimeout(() => setSettled(value), delay)
    return () => window.clearTimeout(handle)
  }, [value, delay])
  return settled
}
