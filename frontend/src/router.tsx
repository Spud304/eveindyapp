import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { AppShell } from './components/AppShell'
import { PlansPage } from './features/plans/PlansPage'
import { PlanPage } from './features/plans/PlanPage'
import { SetupPage } from './features/setup/SetupPage'

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})

const routes = [
  createRoute({ getParentRoute: () => rootRoute, path: '/', component: PlansPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/plans/$planId', component: PlanPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/setup', component: SetupPage }),
]

export const router = createRouter({ routeTree: rootRoute.addChildren(routes) })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
