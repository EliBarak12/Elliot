import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight, MonitorDot, RefreshCw } from "lucide-react";
import { httpJson } from "@/lib/http";
import { tokenToneClass } from "@/lib/tokenRisk";
import {
  type AgentSession,
  type SessionEvent,
  type SessionSignal,
  SESSIONS_QUERY_KEY,
  useSessionStream,
} from "@/hooks/useSessionStream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { FeedbackPanel } from "@/components/FeedbackPanel";
import { TraceHookPanel } from "@/components/TraceHookPanel";
import { cn } from "@/lib/utils";

function tokenTone(tokens: number): string {
  return tokenToneClass(tokens);
}

function signalVariant(severity: string): "destructive" | "warning" | "secondary" {
  if (severity === "high") return "destructive";
  if (severity === "medium") return "warning";
  return "secondary";
}

function sessionBadge(session: AgentSession) {
  if (session.error_count > 0) return { label: "error", variant: "destructive" as const };
  const hasLarge = session.events.some((e) => (e.result_token_estimate ?? 0) > 500);
  if (hasLarge) return { label: "large result", variant: "warning" as const };
  return { label: "ok", variant: "success" as const };
}

/** A labelled block of free text — user prompt, agent output, reasoning. */
function TextBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="space-y-1">
      <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="text-xs text-foreground whitespace-pre-wrap break-words">{text}</p>
    </div>
  );
}

function EventRow({ event }: { event: SessionEvent }) {
  const [open, setOpen] = useState(false);
  const tokens = event.result_token_estimate ?? 0;
  const hasArgs = event.arguments && Object.keys(event.arguments).length > 0;
  const hasDetail = Boolean(
    hasArgs || event.result_preview || event.reasoning || event.error
  );

  return (
    <div className="border-t border-border/40 first:border-t-0">
      <button
        data-testid="event-row"
        disabled={!hasDetail}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "w-full flex items-center gap-2 text-xs py-1.5 pl-9 pr-3 text-left",
          hasDetail && "hover:bg-muted/40 transition-colors"
        )}
      >
        <Badge variant="outline" className="shrink-0 uppercase">
          {event.type === "tools_list" ? "list" : "call"}
        </Badge>
        <span className="font-mono font-medium text-foreground truncate max-w-[12rem]">
          {event.tool_id ?? "tools/list"}
        </span>
        {hasArgs && (
          <span className="text-muted-foreground truncate max-w-[12rem] font-mono text-2xs">
            {JSON.stringify(event.arguments)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-3 shrink-0">
          {event.reasoning && (
            <Badge variant="secondary" className="text-2xs">
              reasoning
            </Badge>
          )}
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
      </button>
      {open && hasDetail && (
        <div className="space-y-3 bg-background/60 px-9 py-3 animate-fade-in-up">
          {event.reasoning && <TextBlock label="Agent reasoning" text={event.reasoning} />}
          {hasArgs && (
            <TextBlock label="Input" text={JSON.stringify(event.arguments, null, 2)} />
          )}
          {event.result_preview && (
            <TextBlock label="Output" text={event.result_preview} />
          )}
          {event.error && <TextBlock label="Error" text={event.error} />}
        </div>
      )}
    </div>
  );
}

function SignalRow({ signals }: { signals: SessionSignal[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {signals.map((sig) => (
        <Badge key={sig.type} variant={signalVariant(sig.severity)} className="text-2xs">
          {sig.message}
        </Badge>
      ))}
    </div>
  );
}

function SessionRow({ session }: { session: AgentSession }) {
  const [expanded, setExpanded] = useState(false);
  const badge = sessionBadge(session);
  const time = new Date(session.started_at * 1000).toLocaleTimeString();
  const signals = session.signals ?? [];

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
        {session.agent_identity?.client ? (
          <div className="flex items-center gap-1.5 shrink-0">
            <Badge variant="outline" className="font-mono text-2xs">
              {session.agent_identity.client}
              {session.agent_identity.client_version
                ? `/${session.agent_identity.client_version}`
                : ""}
            </Badge>
            {session.agent_identity.model && (
              <Badge variant="secondary" className="font-mono text-2xs">
                {session.agent_identity.model}
              </Badge>
            )}
          </div>
        ) : (
          session.agent_hint && (
            <span className="text-xs text-muted-foreground truncate max-w-[10rem]">
              {session.agent_hint}
            </span>
          )
        )}
        {session.source === "hook" && (
          <Badge variant="secondary" className="text-2xs shrink-0">
            hook
          </Badge>
        )}
        <span className="text-2xs text-muted-foreground tabular-nums">{time}</span>
        <div className="ml-auto flex items-center gap-3 shrink-0">
          {signals.length > 0 && (
            <span className="text-2xs text-muted-foreground tabular-nums">
              {signals.length} signal{signals.length === 1 ? "" : "s"}
            </span>
          )}
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
          {(session.summary || signals.length > 0) && (
            <div className="px-9 py-2 space-y-1.5 border-b border-border/40">
              {session.summary && (
                <p className="text-2xs text-muted-foreground">
                  <span className="font-medium text-foreground">Path: </span>
                  <span className="font-mono">{session.summary}</span>
                </p>
              )}
              {signals.length > 0 && <SignalRow signals={signals} />}
            </div>
          )}
          {session.user_prompt && (
            <div className="px-9 py-2.5 border-b border-border/40">
              <TextBlock label="User prompt" text={session.user_prompt} />
            </div>
          )}
          {session.events.map((event, i) => (
            // ts is high-resolution (float seconds) and unique within a
            // session; combining with the type+index gives a stable key.
            <EventRow key={`${event.ts}-${event.type}-${i}`} event={event} />
          ))}
          {session.final_output && (
            <div className="px-9 py-2.5 border-t border-border/40">
              <TextBlock label="Agent output" text={session.final_output} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AgentConsole() {
  useSessionStream();
  const { data, isLoading, refetch, dataUpdatedAt } = useQuery<AgentSession[]>({
    queryKey: [...SESSIONS_QUERY_KEY],
    queryFn: () => httpJson<AgentSession[]>("/v1/sessions?n=20"),
    // useSessionStream() already pushes live snapshot/update frames into this
    // same query cache, so this poll is only a slow fallback for when the SSE
    // stream is unavailable. 60s keeps backend load minimal at scale.
    refetchInterval: 60_000,
  });

  const sessions = Array.isArray(data) ? data : [];
  const largeTokenSessions = sessions.filter((s) =>
    s.events.some((e) => (e.result_token_estimate ?? 0) > 500)
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Console"
        description="Live trace of agent sessions — prompts, reasoning, tool calls, tokens, errors. Install the trace hook below to capture prompts and reasoning from local runs."
        actions={
          <div className="flex items-center gap-3">
            <Badge variant="success" className="gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-success opacity-75 animate-ping" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
              </span>
              Live · {dataUpdatedAt > 0 ? `${Math.floor((Date.now() - dataUpdatedAt) / 1000)}s ago` : "—"}
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

      <TraceHookPanel />

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

      <FeedbackPanel />
    </div>
  );
}
