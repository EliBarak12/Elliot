import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  Database,
  Wrench,
  Zap,
  Package,
  FlaskConical,
  BarChart3,
  ClipboardCheck,
  Circle,
  MonitorDot,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSessionState } from "@/hooks/useSessionState";
import logoUrl from "@/assets/logo.svg";

type NavItem = { to: string; label: string; icon: LucideIcon };

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Build",
    items: [
      { to: "/sources", label: "Sources", icon: Database },
      { to: "/tools", label: "Tools", icon: Wrench },
      { to: "/skills", label: "Skills", icon: Zap },
      { to: "/connector", label: "Connector", icon: Package },
    ],
  },
  {
    label: "Run",
    items: [
      { to: "/playground", label: "Playground", icon: FlaskConical },
      { to: "/console", label: "Agent Console", icon: MonitorDot },
    ],
  },
  {
    label: "Observe",
    items: [
      { to: "/metrics", label: "Metrics", icon: BarChart3 },
      { to: "/evaluation", label: "Evaluation", icon: ClipboardCheck },
    ],
  },
];

interface SessionState {
  connector_built: boolean;
}

export function Sidebar() {
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;
  const { data: sessionRaw } = useSessionState();
  const session = sessionRaw as SessionState | undefined;
  const connectorBuilt = session?.connector_built ?? false;

  return (
    <aside className="flex flex-col w-60 shrink-0 border-r border-border/70 bg-background h-screen">
      <div className="flex items-center gap-2.5 h-14 px-5 border-b border-border/70">
        <img
          src={logoUrl}
          alt=""
          aria-hidden="true"
          className="h-7 w-7 shrink-0"
        />
        <div className="flex flex-col leading-tight">
          <span className="font-semibold text-[15px] tracking-tight text-foreground">Elliot</span>
          <span className="text-2xs text-muted-foreground">Studio</span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-3 px-3 scrollbar-thin space-y-5">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="space-y-0.5">
            <span className="px-2 mb-1.5 inline-block text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground/70">
              {group.label}
            </span>
            {group.items.map(({ to, label, icon: Icon }) => {
              const isActive = to === "/" ? currentPath === "/" : currentPath.startsWith(to);
              return (
                <Link
                  key={to}
                  to={to}
                  className={cn(
                    "flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm font-medium",
                    "transition-all duration-200 ease-apple",
                    isActive
                      ? "bg-accent text-foreground shadow-xs"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0 transition-colors",
                      isActive ? "text-primary" : "text-muted-foreground/80"
                    )}
                  />
                  <span className="truncate">{label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="flex items-center gap-2 px-4 py-3 border-t border-border/70">
        <div className="relative flex items-center justify-center">
          <Circle
            className={cn(
              "h-2 w-2",
              connectorBuilt ? "fill-success text-success" : "fill-muted-foreground/50 text-muted-foreground/50"
            )}
          />
          {connectorBuilt && (
            <span className="absolute h-2 w-2 rounded-full bg-success animate-ping opacity-50" />
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {connectorBuilt ? "Connector built" : "Connector not built"}
        </span>
      </div>
    </aside>
  );
}
