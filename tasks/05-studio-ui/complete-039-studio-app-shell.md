# 039 — App Shell + TanStack Router

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 038

## Objective
Application frame: collapsible sidebar, top header, TanStack Router setup with all 8 page routes.

## Files to Create

### `src/router.tsx`
```tsx
import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { AppShell } from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
import SourcesPage from './pages/SourcesPage'
import ToolsPage from './pages/ToolsPage'
import SkillsPage from './pages/SkillsPage'
import ConnectorPage from './pages/ConnectorPage'
import PlaygroundPage from './pages/PlaygroundPage'
import MetricsPage from './pages/MetricsPage'
import EvaluationPage from './pages/EvaluationPage'

const rootRoute = createRootRoute({ component: AppShell })

const dashboardRoute  = createRoute({ getParentRoute: () => rootRoute, path: '/',           component: Dashboard })
const sourcesRoute    = createRoute({ getParentRoute: () => rootRoute, path: '/sources',    component: SourcesPage })
const toolsRoute      = createRoute({ getParentRoute: () => rootRoute, path: '/tools',      component: ToolsPage })
const skillsRoute     = createRoute({ getParentRoute: () => rootRoute, path: '/skills',     component: SkillsPage })
const connectorRoute  = createRoute({ getParentRoute: () => rootRoute, path: '/connector',  component: ConnectorPage })
const playgroundRoute = createRoute({ getParentRoute: () => rootRoute, path: '/playground', component: PlaygroundPage })
const metricsRoute    = createRoute({ getParentRoute: () => rootRoute, path: '/metrics',    component: MetricsPage })
const evalRoute       = createRoute({ getParentRoute: () => rootRoute, path: '/evaluation', component: EvaluationPage })

const routeTree = rootRoute.addChildren([
  dashboardRoute, sourcesRoute, toolsRoute, skillsRoute,
  connectorRoute, playgroundRoute, metricsRoute, evalRoute,
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
```

### `src/main.tsx`
```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './router'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
)
```

### `src/components/layout/AppShell.tsx`
```tsx
import { Outlet } from '@tanstack/react-router'
import Sidebar from './Sidebar'
import Header from './Header'

export function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
```

### `src/components/layout/Sidebar.tsx`
- Nav items: Dashboard, Sources, Tools, Skills, Connector, Playground, Metrics, Evaluation
- Use `Link` and `useRouterState` from `@tanstack/react-router` for type-safe navigation and active highlighting
- Collapses to icon-only on mobile
- Bottom section: plugin status indicator (green dot = connected, red = disconnected)

### `src/components/layout/Header.tsx`
- Page title derived from current route
- Connector status badge (built / not built)

### Page stubs (each renders a `<h1>` placeholder):
`src/pages/Dashboard.tsx`, `SourcesPage.tsx`, `ToolsPage.tsx`, `SkillsPage.tsx`, `ConnectorPage.tsx`, `PlaygroundPage.tsx`, `MetricsPage.tsx`, `EvaluationPage.tsx`

## Done When
- [ ] All 8 routes render without error
- [ ] Sidebar nav links navigate correctly using `<Link>` from `@tanstack/react-router`
- [ ] Active nav item highlighted via `useRouterState`
- [ ] No TypeScript errors (`tsc --noEmit` passes)
