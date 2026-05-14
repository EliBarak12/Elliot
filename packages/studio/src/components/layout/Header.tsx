import { useRouterState } from "@tanstack/react-router";
import { ChevronRight, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useSessionState } from "@/hooks/useSessionState";
import { useAgentActivity } from "@/hooks/useAgentActivity";
import { ActivityProgressBar } from "./ActivityProgressBar";
import { cn } from "@/lib/utils";

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

  // Watch the session for agent-driven changes (new source / tool / skill /
  // connector built). Fires toasts and lights up the progress bar below.
  // Mounted in the Header (rendered exactly once) so it doesn't double-fire.
  const { isActive } = useAgentActivity();

  return (
    <header className="relative flex items-center justify-between h-14 px-6 border-b border-border/70 bg-background/80 backdrop-blur-md sticky top-0 z-10 shrink-0">
      <div className="flex items-center gap-2 min-w-0">
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
        <Badge
          variant={isActive ? "success" : "muted"}
          className={cn("gap-1.5 transition-colors", isActive && "shadow-[0_0_0_3px_rgba(34,211,238,0.15)]")}
          title={
            isActive
              ? "The agent just changed something — refreshing"
              : "Live — refreshes every few seconds"
          }
        >
          <span
            className={cn(
              "relative flex h-1.5 w-1.5",
              isActive ? "" : ""
            )}
          >
            {isActive && (
              <span className="absolute inline-flex h-full w-full rounded-full bg-success opacity-75 animate-ping" />
            )}
            <span
              className={cn(
                "relative inline-flex h-1.5 w-1.5 rounded-full",
                isActive ? "bg-success" : "bg-muted-foreground/60"
              )}
            />
          </span>
          {isActive ? "Agent active" : "Live"}
        </Badge>
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

      <ActivityProgressBar isActive={isActive} />
    </header>
  );
}
