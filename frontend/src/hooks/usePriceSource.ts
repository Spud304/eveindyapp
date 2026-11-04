import { useState } from 'react'

export type PriceSource = 'jita' | 'average'

const KEY = 'eveindy.prices'

function read(): PriceSource {
  try {
    return window.localStorage.getItem(KEY) === 'average' ? 'average' : 'jita'
  } catch {
    return 'jita'
  }
}

/** Where the shopping list and costs are priced from; remembered in this browser. */
export function usePriceSource(): [PriceSource, (p: PriceSource) => void] {
  const [prices, setPrices] = useState<PriceSource>(read)
  const set = (p: PriceSource) => {
    setPrices(p)
    try {
      window.localStorage.setItem(KEY, p)
    } catch {
      // private window or blocked storage: the choice lasts for this page only
    }
  }
  return [prices, set]
}
