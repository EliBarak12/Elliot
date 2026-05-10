import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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

function tokenColor(tokens: number): string {
  if (tokens > 1000) return "text-red-600";
  if (tokens > 300) return "text-yellow-600";
  return "text-green-600";
}

function sessionStatus(session: AgentSession): { label: string; color: string } {
  if (session.error_count > 0) return { label: "error", color: "destructive" };
  const hasLarge = session.events.some((e) => (e.result_token_estimate ?? 0) > 500);
  if (hasLarge) return { label: "large result", color: "outline" };
  return { label: "ok", color: "secondary" };
}

function EventRow({ event }: { event: SessionEvent }) {
  const tokens = event.result_token_estimate ?? 0;
  return (
    <div className="flex items-center gap-2 text-xs py-0.5 pl-6 text-muted-foreground">
      <Badge variant="outline" className="text-xs shrink-0">
        {event.type === "tools_list" ? "list" : "call"}
      </Badge>
      <span className="font-medium text-foreground">
        {event.tool_id ?? "tools/list"}
      </span>
      {event.arguments && Object.keys(event.arguments).length > 0 && (
        <span className="truncate max-w-48">
          {JSON.stringify(event.arguments)}
        </span>
      )}
      {event.result_rows != null && (
        <span>{event.result_rows} rows</span>
      )}
      {tokens > 0 && (
        <span className={tokenColor(tokens)}>{tokens} tok</span>
      )}
      <span>{event.duration_ms.toFixed(0)}ms</span>
      {event.error && (
        <span className="text-destructive truncate max-w-40">{event.error}</span>
      )}
    </div>
  );
}

function SessionRow({ session }: { session: AgentSession }) {
  const [expanded, setExpanded] = useState(false);
  const status = sessionStatus(session);
  const time = new Date(session.started_at * 1000).toLocaleTimeString();

  return (
    <div className="border-b last:border-0">
      <button
        data-testid="session-row"
        className="w-full text-left flex items-center gap-3 px-3 py-2 hover:bg-accent text-xs"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="font-mono font-medium">{session.session_id}</span>
        {session.agent_hint && (
          <span className="text-muted-foreground">{session.agent_hint}</span>
        )}
        <span className="text-muted-foreground">{time}</span>
        <span>{session.total_tool_calls} calls</span>
        <span className={tokenColor(session.total_tokens_estimated)}>
          {session.total_tokens_estimated} tok
        </span>
        <span>{session.total_duration_ms.toFixed(0)}ms</span>
        <Badge variant={status.color as "destructive" | "outline" | "secondary"} className="ml-auto text-xs">
          {status.label}
        </Badge>
      </button>
      {expanded && (
        <div className="pb-2">
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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Agent Console</h2>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
            Live
          </span>
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            Refresh
          </Button>
        </div>
      </div>

      {largeTokenSessions.length > 0 && (
        <div className="rounded-md border border-yellow-300 bg-yellow-50 px-4 py-2 text-sm text-yellow-800">
          {largeTokenSessions.map((s) => {
            const largeTool = s.events.find((e) => (e.result_token_estimate ?? 0) > 500);
            return (
              <p key={s.session_id}>
                ⚠ Session <strong>{s.session_id}</strong>:{" "}
                <strong>{largeTool?.tool_id}</strong> returned{" "}
                {largeTool?.result_token_estimate} tokens. Consider adding LIMIT.
              </p>
            );
          })}
        </div>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            Sessions
            {dataUpdatedAt > 0 && (
              <span className="ml-2 font-normal text-muted-foreground text-xs">
                updated {new Date(dataUpdatedAt).toLocaleTimeString()}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && (
            <p className="text-sm text-muted-foreground px-4 py-8 text-center">Loading…</p>
          )}
          {!isLoading && sessions.length === 0 && (
            <p className="text-sm text-muted-foreground px-4 py-8 text-center">
              No agent sessions yet. Connect an agent to your connector runtime.
            </p>
          )}
          {sessions.map((session) => (
            <SessionRow key={session.session_id} session={session} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
