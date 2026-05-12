import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight, MonitorDot, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface SessionEvent {
  ts: number;
  type: "tools_list" | "tool_call";
  tool_id: string | null;
  arguments: Record<string, unknown> | null;
  result_rows: number | null;
  result_token_estimate: number | null;
  duration_ms: number;
  error: string | null;
}

interface AgentSession {
  session_id: string;
  started_at: number;
  agent_hint: string | null;
  events: SessionEvent[];
  total_tool_calls: number;
  total_tokens_estimated: number;
  total_duration_ms: number;
  error_count: number;
}

function tokenTone(tokens: number): string {
  if (tokens > 1000) return "text-destructive";
  if (tokens > 300) return "text-warning";
  return "text-success";
}

function sessionBadge(session: AgentSession) {
  if (session.error_count > 0) return { label: "error", variant: "destructive" as const };
  const hasLarge = session.events.some((e) => (e.result_token_estimate ?? 0) > 500);
  if (hasLarge) return { label: "large result", variant: "warning" as const };
  return { label: "ok", variant: "success" as const };
}

function EventRow({ event }: { event: SessionEvent }) {
  const tokens = event.result_token_estimate ?? 0;
  return (
    <div className="flex items-center gap-2 text-xs py-1 pl-9 pr-3">
      <Badge variant="outline" className="shrink-0 uppercase">
        {event.type === "tools_list" ? "list" : "call"}
      </Badge>
      <span className="font-mono font-medium text-foreground truncate max-w-[12rem]">
        {event.tool_id ?? "tools/list"}
      </span>
      {event.arguments && Object.keys(event.arguments).length > 0 && (
        <span className="text-muted-foreground truncate max-w-[12rem] font-mono text-2xs">
          {JSON.stringify(event.arguments)}
        </span>
      )}
      <div className="ml-auto flex items-center gap-3 shrink-0">
        {event.result_rows != null && (
          <span className="text-muted-foreground tabular-nums">{event.result_rows} rows</span>
        )}
        {tokens > 0 && (
          <span className={cn("tabular-nums font-medium", tokenTone(tokens))}>{tokens} tok</span>
        )}
        <span className="text-muted-foreground tabular-nums w-12 text-right">
          {event.duration_ms.toFixed(0)}ms
        </span>
        {event.error && (
          <Badge variant="destructive" className="shrink-0">
            error
          </Badge>
        )}
      </div>
    </div>
  );
}

function SessionRow({ session }: { session: AgentSession }) {
  const [expanded, setExpanded] = useState(false);
  const badge = sessionBadge(session);
  const time = new Date(session.started_at * 1000).toLocaleTimeString();

  return (
    <div className="border-b border-border/60 last:border-0 first:rounded-t-xl last:rounded-b-xl overflow-hidden">
      <button
        data-testid="session-row"
        className={cn(
          "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/40"
        )}
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        )}
        <span className="font-mono text-xs font-medium text-foreground shrink-0">
          {session.session_id}
        </span>
        {session.agent_hint && (
          <span className="text-xs text-muted-foreground truncate max-w-[10rem]">
            {session.agent_hint}
          </span>
        )}
        <span className="text-2xs text-muted-foreground tabular-nums">{time}</span>
        <div className="ml-auto flex items-center gap-3 shrink-0">
          <span className="text-xs text-muted-foreground tabular-nums">
            {session.total_tool_calls} calls
          </span>
          <span
            className={cn(
              "text-xs tabular-nums font-medium",
              tokenTone(session.total_tokens_estimated)
            )}
          >
            {session.total_tokens_estimated} tok
          </span>
          <span className="text-xs text-muted-foreground tabular-nums w-14 text-right">
            {session.total_duration_ms.toFixed(0)}ms
          </span>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
      </button>
      {expanded && (
        <div className="bg-muted/30 py-1 animate-fade-in-up">
          {session.events.map((event, i) => (
            <EventRow key={i} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function AgentConsole() {
  const { data, isLoading, refetch, dataUpdatedAt } = useQuery<AgentSession[]>({
    queryKey: ["sessions"],
    queryFn: async () => {
      const r = await fetch("http://localhost:3001/v1/sessions?n=20");
      if (!r.ok) throw new Error("Failed to fetch sessions");
      return r.json() as Promise<AgentSession[]>;
    },
    refetchInterval: 5_000,
  });

  const sessions = Array.isArray(data) ? data : [];
  const largeTokenSessions = sessions.filter((s) =>
    s.events.some((e) => (e.result_token_estimate ?? 0) > 500)
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Console"
        description="Live trace of agent sessions — tool calls, tokens, latencies, errors."
        actions={
          <div className="flex items-center gap-3">
            <Badge variant="success" className="gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-success opacity-75 animate-ping" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
              </span>
              Live · {Math.floor((Date.now() - (dataUpdatedAt || Date.now())) / 1000)}s ago
            </Badge>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void refetch()}
              className="gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        }
      />

      {largeTokenSessions.length > 0 && (
        <Card className="border-warning/40 bg-warning/5">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-warning/10 text-warning shrink-0">
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div className="space-y-1">
                {largeTokenSessions.map((s) => {
                  const largeTool = s.events.find((e) => (e.result_token_estimate ?? 0) > 500);
                  return (
                    <p key={s.session_id} className="text-sm text-foreground">
                      Session <span className="font-mono font-medium">{s.session_id}</span>:{" "}
                      <span className="font-mono">{largeTool?.tool_id}</span> returned{" "}
                      <span className="font-semibold text-warning">
                        {largeTool?.result_token_estimate} tokens
                      </span>
                      . Consider adding LIMIT.
                    </p>
                  );
                })}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>
            Sessions
            {sessions.length > 0 && (
              <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">
                ({sessions.length})
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && (
            <div className="space-y-2 px-4 pb-4">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}
          {!isLoading && sessions.length === 0 && (
            <div className="px-4 pb-4">
              <EmptyState
                icon={MonitorDot}
                title="No agent sessions yet"
                description="Connect an agent to your connector runtime — sessions will stream in live."
                className="border-0 bg-transparent"
              />
            </div>
          )}
          {sessions.map((session) => (
            <SessionRow key={session.session_id} session={session} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
