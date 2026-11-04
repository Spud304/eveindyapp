import { useEffect, useState } from 'react'

/** The current time, updated every `ms`, so countdowns keep moving while the data does not
 * change (a refetch with the same data does not re-render). */
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(t)
  }, [ms])
  return now
}
