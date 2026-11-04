import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { AppShell } from './components/AppShell'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { LibraryPage } from './features/library/LibraryPage'
import { PlansPage } from './features/plans/PlansPage'
import { PlanPage } from './features/plans/PlanPage'
import { PlanViewPage, SharedLinkPage } from './features/plans/SharedPlanPage'
import { SetupPage } from './features/setup/SetupPage'

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})

const routes = [
  createRoute({ getParentRoute: () => rootRoute, path: '/', component: DashboardPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/plans', component: PlansPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/library', component: LibraryPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/plans/$planId', component: PlanPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/plans/$planId/view', component: PlanViewPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/shared/$token', component: SharedLinkPage }),
  createRoute({ getParentRoute: () => rootRoute, path: '/setup', component: SetupPage }),
]

export const router = createRouter({ routeTree: rootRoute.addChildren(routes) })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
