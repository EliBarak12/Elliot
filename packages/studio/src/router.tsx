import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { AppShell } from "./components/layout/AppShell";
import { ErrorFallback } from "./components/layout/ErrorBoundary";
import Dashboard from "./pages/Dashboard";
import SourcesPage from "./pages/SourcesPage";
import ToolsPage from "./pages/ToolsPage";
import SkillsPage from "./pages/SkillsPage";
import ConnectorPage from "./pages/ConnectorPage";
import PlaygroundPage from "./pages/PlaygroundPage";
import MetricsPage from "./pages/MetricsPage";
import EvaluationPage from "./pages/EvaluationPage";
import AgentConsole from "./pages/AgentConsole";

const rootRoute = createRootRoute({ component: AppShell });

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Dashboard,
});
const sourcesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sources",
  component: SourcesPage,
});
const toolsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tools",
  component: ToolsPage,
});
const skillsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/skills",
  component: SkillsPage,
});
const connectorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/connector",
  component: ConnectorPage,
});
const playgroundRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/playground",
  component: PlaygroundPage,
});
const metricsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/metrics",
  component: MetricsPage,
});
const evalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/evaluation",
  component: EvaluationPage,
});
const consoleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/console",
  component: AgentConsole,
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  sourcesRoute,
  toolsRoute,
  skillsRoute,
  connectorRoute,
  playgroundRoute,
  metricsRoute,
  evalRoute,
  consoleRoute,
]);

export const router = createRouter({
  routeTree,
  // Catch errors thrown in route components/loaders so a single throw renders a
  // friendly fallback instead of white-screening the app.
  defaultErrorComponent: () => <ErrorFallback />,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export { Outlet };
