# 039 — App Shell + Router

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 038

## Objective
Application frame: collapsible sidebar, top header, React Router setup with all 8 page routes.

## Files to Create

### `src/router.tsx`
See DEVELOPMENT_GUIDE.md §6.5. Routes: `/` (Dashboard), `/sources`, `/tools`, `/skills`, `/connector`, `/playground`, `/metrics`, `/evaluation`. All wrapped in `<AppShell>`.

### `src/main.tsx`
`QueryClientProvider` → `RouterProvider`. See DEVELOPMENT_GUIDE.md §6.5.

### `src/components/layout/AppShell.tsx`
- Two-column layout: fixed sidebar (240px) + main content area
- `<Outlet />` renders active page
- Sidebar collapses to icon-only on mobile

### `src/components/layout/Sidebar.tsx`
- Nav items: Dashboard, Sources, Tools, Skills, Connector, Playground, Metrics, Evaluation
- Active item highlighted
- Bottom section: plugin status indicator (green dot = connected, red = disconnected)

### `src/components/layout/Header.tsx`
- Page title (from route)
- Connector status badge (built / not built)

### Page stubs (each renders a `<h1>` placeholder):
`src/pages/Dashboard.tsx`, `SourcesPage.tsx`, `ToolsPage.tsx`, `SkillsPage.tsx`, `ConnectorPage.tsx`, `PlaygroundPage.tsx`, `MetricsPage.tsx`, `EvaluationPage.tsx`

## Done When
- [ ] All 8 routes render without error
- [ ] Sidebar nav links navigate correctly
- [ ] No TypeScript errors
