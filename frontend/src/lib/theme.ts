export type Theme = 'light' | 'dark'

const KEY = 'eveindy.theme'

/** Light unless this browser chose dark; storage can be blocked, so failures mean light. */
export function readTheme(): Theme {
  try {
    return window.localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

/** Sets the root attribute the CSS tokens key on and remembers the choice for this browser. */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  try {
    window.localStorage.setItem(KEY, theme)
  } catch {
    // no storage: the page still switches for this visit
  }
}
