// Live agent-session feed for the Agent Console.
//
// The connector runtime pushes session updates over Server-Sent Events at
// /v1/sessions/stream. EventSource cannot send the X-Elliot-Key header, so we
// consume the stream with a fetch ReadableStream instead and merge each frame
// into the React Query cache the polling query also writes to.
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { httpFetch } from "@/lib/http";

export interface SessionEvent {
  ts: number;
  type: "tools_list" | "tool_call";
  tool_id: string | null;
  arguments: Record<string, unknown> | null;
  result_rows: number | null;
  result_token_estimate: number | null;
  duration_ms: number;
  error: string | null;
  result_preview?: string | null;
  reasoning?: string | null;
}

export interface AgentIdentity {
  client?: string | null;
  client_version?: string | null;
  model?: string | null;
  modality?: string | null;
  user_agent?: string | null;
}

export interface SessionSignal {
  type: string;
  severity: "high" | "medium" | "low";
  message: string;
}

export interface AgentSession {
  session_id: string;
  started_at: number;
  last_activity?: number;
  agent_hint: string | null;
  agent_identity?: AgentIdentity | null;
  events: SessionEvent[];
  total_tool_calls: number;
  total_tokens_estimated: number;
  total_duration_ms: number;
  error_count: number;
  signals?: SessionSignal[];
  summary?: string;
  /** "mcp" — observed from the wire; "hook" — ingested from a harness hook. */
  source?: string;
  user_prompt?: string | null;
  final_output?: string | null;
}

export const SESSIONS_QUERY_KEY = ["sessions"] as const;

function mergeSession(list: AgentSession[], incoming: AgentSession): AgentSession[] {
  const next = list.filter((s) => s.session_id !== incoming.session_id);
  next.push(incoming);
  next.sort((a, b) => b.started_at - a.started_at);
  return next;
}

interface SseFrame {
  event: string;
  data: unknown;
}

function parseFrame(frame: string): SseFrame | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) as unknown };
  } catch {
    console.error("[useSessionStream] bad SSE frame");
    return null;
  }
}

/**
 * Subscribe the Agent Console's ["sessions"] query to the live SSE feed.
 * Falls back silently to the polling query if the stream is unavailable.
 */
export function useSessionStream(): void {
  const qc = useQueryClient();
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let backoff = 0;

    async function consume(): Promise<void> {
      const resp = await httpFetch("/v1/sessions/stream", {
        signal: controller.signal,
        headers: { Accept: "text/event-stream" },
      });
      if (!resp.ok || !resp.body) return;
      backoff = 0;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const parsed = parseFrame(frame);
          if (!parsed) continue;
          if (parsed.event === "snapshot") {
            qc.setQueryData<AgentSession[]>(
              [...SESSIONS_QUERY_KEY],
              parsed.data as AgentSession[]
            );
          } else if (parsed.event === "update") {
            qc.setQueryData<AgentSession[]>([...SESSIONS_QUERY_KEY], (old) =>
              mergeSession(old ?? [], parsed.data as AgentSession)
            );
          }
        }
      }
    }

    async function loop(): Promise<void> {
      while (!cancelled) {
        try {
          await consume();
        } catch {
          // network or stream error — retry with backoff below
        }
        if (cancelled) break;
        backoff = Math.min(backoff + 1, 5);
        await new Promise((resolve) => setTimeout(resolve, backoff * 2000));
      }
    }
    void loop();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [qc]);
}
