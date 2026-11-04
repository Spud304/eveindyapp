import { useEffect, useState } from 'react'

/**
 * A local copy of a server value for inputs that save on change (checkboxes, selects).
 * The copy changes at once when the user acts; it follows the server value whenever that
 * changes (a refetch, or a rollback after a refused save). Without it a controlled input
 * snaps back for a frame until the mutation's cache update renders.
 */
export function useLocalCopy<T>(server: T): [T, (next: T) => void] {
  const [value, setValue] = useState(server)
  const key = JSON.stringify(server)
  useEffect(() => {
    setValue(JSON.parse(key) as T)
  }, [key])
  return [value, setValue]
}
