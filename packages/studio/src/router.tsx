import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { AppShell } from "./components/layout/AppShell";
import Dashboard from "./pages/Dashboard";
import SourcesPage from "./pages/SourcesPage";
import ToolsPage from "./pages/ToolsPage";
import SkillsPage from "./pages/SkillsPage";
import ConnectorPage from "./pages/ConnectorPage";
import PlaygroundPage from "./pages/PlaygroundPage";
import MetricsPage from "./pages/MetricsPage";
import EvaluationPage from "./pages/EvaluationPage";

const rootRoute = createRootRoute({ component: AppShell });

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/" });
const dashboardRoute = createRoute({
  getParentRoute: () => indexRoute,
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

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  sourcesRoute,
  toolsRoute,
  skillsRoute,
  connectorRoute,
  playgroundRoute,
  metricsRoute,
  evalRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export { Outlet };
