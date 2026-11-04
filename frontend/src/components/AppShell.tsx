import { useState, type ReactNode } from 'react'
import { Link, useLocation } from '@tanstack/react-router'
import clsx from 'clsx'
import { useMe } from '@/lib/api/hooks'
import { logout } from '@/lib/api/client'
import { Badge, Empty, LinkButton } from '@/components/ui'
import { applyTheme, readTheme, type Theme } from '@/lib/theme'

const NAV = [
  { to: '/', label: 'Dashboard', id: 'dashboard' },
  { to: '/plans', label: 'Plans', id: 'plans' },
  { to: '/library', label: 'Library', id: 'library' },
  { to: '/setup', label: 'Setup', id: 'setup' },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe()
  const { pathname } = useLocation()
  const [theme, setTheme] = useState<Theme>(readTheme)
  const toggleTheme = () => {
    const next: Theme = theme === 'light' ? 'dark' : 'light'
    applyTheme(next)
    setTheme(next)
  }
  const authed = me.data?.authenticated
  const main = me.data?.characters.find((c) => c.is_main)
  const needsLink = authed && !me.data?.characters.some((c) => c.esi)
  const active = (to: string) => (to === '/' ? pathname === '/' : pathname.startsWith(to))
  // A plan shared by link opens without logging in.
  const open = pathname.startsWith('/shared/')
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-10 items-center gap-4 border-b border-line bg-panel px-3">
        <Link to="/" className="font-semibold tracking-tight">
          EVE Indy
        </Link>
        {authed ? (
          <nav className="flex items-center gap-1">
            {NAV.map((n) => (
              <Link key={n.to} to={n.to} data-testid={`nav.${n.id}`} className={clsx('rounded px-2 py-1 text-muted hover:bg-panel-2 hover:text-fg', active(n.to) && 'bg-panel-2 text-fg')}>
                {n.label}
              </Link>
            ))}
          </nav>
        ) : null}
        <div className="ml-auto flex items-center gap-3 text-muted">
          <button type="button" onClick={toggleTheme} className="hover:text-fg" data-testid="shell.theme" data-theme-now={theme} title="switch between light and dark">
            {theme === 'light' ? 'Dark' : 'Light'}
          </button>
          {me.isLoading ? null : authed ? (
            <>
              <span className="flex items-center gap-1.5">
                <span data-testid="shell.user">{me.data?.display_name}</span>
                {needsLink ? (
                  <Badge tone="warn" testId="shell.no-esi" title="no character has granted ESI access yet">
                    no esi
                  </Badge>
                ) : null}
              </span>
              <button type="button" onClick={() => void logout()} className="hover:text-fg" data-testid="shell.logout">
                Log out
              </button>
            </>
          ) : null}
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-auto p-4">
        {me.isLoading ? null : authed || open ? (
          children
        ) : (
          <Empty
            testId="shell.signed-out"
            hint="Plans use your characters' skills, blueprints and corp hangars, so the app needs to know who you are."
            action={
              me.data?.sso_configured === false ? (
                <span className="text-bad">EVE SSO is not configured on the server.</span>
              ) : (
                <LinkButton href={`/auth/login?next=${encodeURIComponent(pathname)}`} testId="shell.login">
                  Log in with EVE Online
                </LinkButton>
              )
            }
          >
            Not logged in.
          </Empty>
        )}
      </main>
      <footer className="flex h-6 items-center justify-end gap-3 border-t border-line px-3 text-label text-muted">
        {main ? <span>main: {main.name}</span> : null}
        <span>eveindy {me.data?.version ?? ''}</span>
      </footer>
    </div>
  )
}
