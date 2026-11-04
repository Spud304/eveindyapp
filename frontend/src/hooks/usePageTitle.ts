import { useEffect } from 'react'

const APP = 'EVE Indy'

/** Browser tab reads "Page · EVE Indy". */
export function usePageTitle(title: string | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP}` : APP
    return () => {
      document.title = APP
    }
  }, [title])
}
