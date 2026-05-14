import { useRouterState } from "@tanstack/react-router";
import { ChevronRight, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useSessionState } from "@/hooks/useSessionState";
import logoUrl from "@/assets/logo.svg";

const ROUTE_META: Record<string, { title: string; section?: string }> = {
  "/": { title: "Dashboard", section: "Overview" },
  "/sources": { title: "Sources", section: "Build" },
  "/tools": { title: "Tools", section: "Build" },
  "/skills": { title: "Skills", section: "Build" },
  "/connector": { title: "Connector", section: "Build" },
  "/playground": { title: "Playground", section: "Run" },
  "/console": { title: "Agent Console", section: "Run" },
  "/metrics": { title: "Metrics", section: "Observe" },
  "/evaluation": { title: "Evaluation", section: "Observe" },
};

interface SessionState {
  connector_built: boolean;
}

export function Header() {
  const routerState = useRouterState();
  const path = routerState.location.pathname;
  const meta = ROUTE_META[path] ?? { title: "Elliot Studio" };

  const { data: sessionRaw } = useSessionState();
  const session = sessionRaw as SessionState | undefined;
  const connectorBuilt = session?.connector_built ?? false;

  return (
    <header className="flex items-center justify-between h-14 px-6 border-b border-border/70 bg-background/80 backdrop-blur-md sticky top-0 z-10 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <img
          src={logoUrl}
          alt="Elliot"
          className="h-6 w-6 shrink-0"
        />
        {meta.section && (
          <>
            <span className="text-sm text-muted-foreground truncate">{meta.section}</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
          </>
        )}
        <h1 className="text-sm font-semibold tracking-tight text-foreground truncate">
          {meta.title}
        </h1>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="hidden md:flex items-center gap-2 h-8 px-2.5 rounded-md border border-input bg-card text-muted-foreground text-xs shadow-xs hover:bg-accent/50 transition-colors"
          aria-label="Search"
        >
          <Search className="h-3.5 w-3.5" />
          <span>Search</span>
          <kbd className="ml-2 rounded border border-border bg-muted px-1.5 py-0.5 text-2xs font-mono text-muted-foreground">
            ⌘K
          </kbd>
        </button>
        <Badge variant={connectorBuilt ? "success" : "muted"} className="gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${connectorBuilt ? "bg-success" : "bg-muted-foreground/60"}`}
          />
          {connectorBuilt ? "Connector live" : "Connector not built"}
        </Badge>
      </div>
    </header>
  );
}
