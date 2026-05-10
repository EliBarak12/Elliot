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
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/sources", label: "Sources", icon: Database },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/skills", label: "Skills", icon: Zap },
  { to: "/connector", label: "Connector", icon: Package },
  { to: "/playground", label: "Playground", icon: FlaskConical },
  { to: "/metrics", label: "Metrics", icon: BarChart3 },
  { to: "/console", label: "Agent Console", icon: MonitorDot },
  { to: "/evaluation", label: "Evaluation", icon: ClipboardCheck },
] as const;

export function Sidebar() {
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  return (
    <aside className="flex flex-col w-56 shrink-0 border-r bg-background h-screen">
      <div className="flex items-center h-14 px-4 border-b">
        <span className="font-bold text-lg tracking-tight">Elliot</span>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
          const isActive = to === "/" ? currentPath === "/" : currentPath.startsWith(to);
          return (
            <Link
              key={to}
              to={to}
              className={cn(
                "flex items-center gap-3 px-4 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                isActive && "bg-accent text-accent-foreground"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center gap-2 px-4 py-3 border-t text-xs text-muted-foreground">
        <Circle className="h-2 w-2 fill-red-500 text-red-500" />
        Plugin disconnected
      </div>
    </aside>
  );
}
