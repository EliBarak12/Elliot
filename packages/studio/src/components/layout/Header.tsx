import { useRouterState } from "@tanstack/react-router";
import { Badge } from "@/components/ui/badge";

const ROUTE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/sources": "Sources",
  "/tools": "Tools",
  "/skills": "Skills",
  "/connector": "Connector",
  "/playground": "Playground",
  "/metrics": "Metrics",
  "/evaluation": "Evaluation",
};

export function Header() {
  const routerState = useRouterState();
  const path = routerState.location.pathname;
  const title = ROUTE_TITLES[path] ?? "Elliot Studio";

  return (
    <header className="flex items-center justify-between h-14 px-6 border-b bg-background shrink-0">
      <h1 className="text-base font-semibold">{title}</h1>
      <Badge variant="outline" className="text-xs text-muted-foreground">
        Connector: not built
      </Badge>
    </header>
  );
}
