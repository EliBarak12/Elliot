import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  CheckCircle2,
  Circle,
  Database,
  FlaskConical,
  Package,
  Wrench,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/ui/stat-card";
import { AgentOnboarding } from "@/components/dashboard/AgentOnboarding";
import { useSessionState } from "@/hooks/useSessionState";
import { httpJson } from "@/lib/http";
import { cn } from "@/lib/utils";

interface SessionState {
  source_count: number;
  tool_count: number;
  skill_count: number;
  connector_built: boolean;
}

interface AuditEntry {
  ts: number;
  tool_id: string;
  result_row_count: number;
  duration_ms: number;
  error?: string;
}

export default function Dashboard() {
  const { data: sessionRaw } = useSessionState();
  const session = sessionRaw as SessionState | undefined;

  // Recent activity is *tool invocations*, which execute on the runtime — so
  // read the runtime's audit log, not the plugin's build-action log. Falls
  // back to an empty list when the runtime is not up yet.
  const { data: auditRaw } = useQuery({
    queryKey: ["recent-tool-calls"],
    queryFn: () => httpJson<AuditEntry[]>("/v1/audit?n=10").catch(() => [] as AuditEntry[]),
    refetchInterval: 10_000,
  });
  const auditEntries = Array.isArray(auditRaw) ? (auditRaw as AuditEntry[]) : [];

  const sourceCount = session?.source_count ?? 0;
  const toolCount = session?.tool_count ?? 0;
  const skillCount = session?.skill_count ?? 0;
  const connectorBuilt = session?.connector_built ?? false;

  const completedSteps = [sourceCount > 0, toolCount > 0, connectorBuilt].filter(Boolean).length;
  const totalSteps = 3;
  // Onboarding stays prominent until the agent has actually produced something.
  // Once a connector is built (or audit entries exist), shrink it to a one-line
  // reconnect hint so the dashboard becomes pure observability.
  const agentHasProduced = connectorBuilt || auditEntries.length > 0;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Dashboard"
        description="Elliot is agent-first. Your agent builds — this page shows what it built and how it's behaving in production."
      />

      <AgentOnboarding compact={agentHasProduced} />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Sources" value={sourceCount} icon={Database} tone="primary" />
        <StatCard label="Tools" value={toolCount} icon={Wrench} />
        <StatCard label="Skills" value={skillCount} icon={Zap} />
        <StatCard
          label="Connector"
          value={connectorBuilt ? "Live" : "Idle"}
          icon={Package}
          tone={connectorBuilt ? "success" : "default"}
          hint={connectorBuilt ? "Ready to serve" : "Not built yet"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <CardTitle>What your agent has built</CardTitle>
                <CardDescription>
                  {completedSteps === totalSteps
                    ? "All set. Keep an eye on Recent activity below."
                    : `Step ${completedSteps} of ${totalSteps} — your agent will fill these in as it works.`}
                </CardDescription>
              </div>
              <Badge variant={completedSteps === totalSteps ? "success" : "muted"}>
                {Math.round((completedSteps / totalSteps) * 100)}%
              </Badge>
            </div>
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500 ease-apple"
                style={{ width: `${(completedSteps / totalSteps) * 100}%` }}
              />
            </div>
          </CardHeader>
          <CardContent className="space-y-1">
            <AgentStep
              done={sourceCount > 0}
              label="Data source connected"
              description="Ask your agent: 'discover the schema at https://api.example.com'."
              icon={Database}
            />
            <AgentStep
              done={toolCount > 0}
              label="Tool drafted"
              description="The agent calls elliot_create_tool to define a verb-first contract."
              icon={Wrench}
            />
            <AgentStep
              done={connectorBuilt}
              label="Connector built"
              description="The agent bundles everything and starts the runtime."
              icon={Package}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Manual escape hatches</CardTitle>
            <CardDescription>
              You shouldn't need these — but they're here if you want to inspect or override.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <QuickAction
              icon={Database}
              label="View sources"
              href="/sources"
              description="See what your agent discovered"
            />
            <QuickAction
              icon={Wrench}
              label="View tools"
              href="/tools"
              description="Inspect the contracts your agent drafted"
            />
            <QuickAction
              icon={FlaskConical}
              label="Open playground"
              href="/playground"
              description="Run a tool yourself, see results"
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>Recent activity</CardTitle>
              <CardDescription>
                The last {Math.min(auditEntries.length, 10)} tool invocations
              </CardDescription>
            </div>
            {auditEntries.length > 0 && (
              <Link to="/console">
                <Button variant="ghost" size="sm" className="gap-1">
                  View all
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </Button>
              </Link>
            )}
          </div>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {auditEntries.length === 0 ? (
            <div className="px-5 pb-5 pt-2 text-center">
              <p className="text-sm text-muted-foreground">
                No activity yet. Try a tool in the{" "}
                <Link to="/playground" className="text-foreground font-medium hover:underline">
                  Playground
                </Link>
                .
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border/60">
              {auditEntries.map((entry, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 px-5 py-2.5 hover:bg-muted/40 transition-colors"
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full shrink-0",
                      entry.error ? "bg-destructive" : "bg-success"
                    )}
                  />
                  <span className="font-mono text-2xs text-muted-foreground tabular-nums w-20 shrink-0">
                    {new Date(entry.ts * 1000).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                  <span className="text-sm font-medium text-foreground truncate flex-1 min-w-0">
                    {entry.tool_id}
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {entry.result_row_count} rows
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums w-14 text-right">
                    {entry.duration_ms.toFixed(0)}ms
                  </span>
                  {entry.error && (
                    <Badge variant="destructive" className="shrink-0">
                      error
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function AgentStep({
  done,
  label,
  description,
  icon: Icon,
}: {
  done: boolean;
  label: string;
  description: string;
  icon: typeof Database;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg px-3 py-2.5 -mx-2">
      {done ? (
        <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
      ) : (
        <Circle className="h-5 w-5 text-muted-foreground/40 shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        <p
          className={cn(
            "text-sm font-medium",
            done ? "text-muted-foreground line-through" : "text-foreground"
          )}
        >
          {label}
        </p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Icon className="h-4 w-4 text-muted-foreground/60 shrink-0" />
    </div>
  );
}

function QuickAction({
  icon: Icon,
  label,
  description,
  href,
}: {
  icon: typeof Database;
  label: string;
  description: string;
  href: string;
}) {
  return (
    <Link
      to={href}
      className="group flex items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 -mx-2 transition-all hover:bg-muted/60 hover:border-border"
    >
      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary transition-colors">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground/60 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
    </Link>
  );
}
