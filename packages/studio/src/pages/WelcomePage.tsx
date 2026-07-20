import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { Activity, CheckCircle2, Play, Wrench } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { AgentOnboarding } from "@/components/dashboard/AgentOnboarding";
import { useCallRuntimeTool, useRuntimeTools } from "@/hooks/useRuntimeTools";
import type { RuntimeTool } from "@/lib/runtime-mcp";
import { cn } from "@/lib/utils";

export const WELCOME_DISMISSED_KEY = "elliot.welcome.dismissed";

/** The demo tool the tour runs; falls back to the first READ tool so the tour
 * still works when the operator swapped the demo connector for their own. */
const PREFERRED_TOOL_ID = "get_customer_overview";
const PREFERRED_ARGS: Record<string, unknown> = { customer_id: 1 };

export function dismissWelcome(): void {
  try {
    localStorage.setItem(WELCOME_DISMISSED_KEY, "true");
  } catch (err) {
    console.warn("[welcome] could not persist dismissal", err);
  }
}

export function isWelcomeDismissed(): boolean {
  try {
    return localStorage.getItem(WELCOME_DISMISSED_KEY) === "true";
  } catch {
    return false;
  }
}

interface RunOutcome {
  result: unknown;
  latencyMs: number;
}

function tokenEstimateOf(result: unknown): number | null {
  if (result && typeof result === "object" && "meta" in result) {
    const meta = (result as { meta?: Record<string, unknown> }).meta;
    const estimate = meta?.token_estimate ?? meta?.result_token_estimate;
    return typeof estimate === "number" ? estimate : null;
  }
  return null;
}

function StepBadge({ number, done }: { number: number; done: boolean }) {
  return (
    <div
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold",
        done ? "bg-primary text-primary-foreground" : "bg-primary/10 text-primary",
      )}
    >
      {done ? <CheckCircle2 className="h-4 w-4" /> : number}
    </div>
  );
}

export default function WelcomePage() {
  const navigate = useNavigate();
  // The tour calls the RUNTIME (where the preloaded demo connector lives),
  // not the builder session — which is legitimately empty on a fresh install.
  const { data: toolsRaw } = useRuntimeTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as RuntimeTool[]) : [];
  const demoTool = tools.find((t) => t.id === PREFERRED_TOOL_ID) ?? tools[0] ?? null;

  const { mutateAsync: callTool, isPending } = useCallRuntimeTool();
  const [outcome, setOutcome] = useState<RunOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runDemoTool = async () => {
    if (!demoTool) return;
    setError(null);
    const args = demoTool.id === PREFERRED_TOOL_ID ? PREFERRED_ARGS : {};
    const started = performance.now();
    try {
      const result = await callTool({ name: demoTool.id, args });
      setOutcome({ result, latencyMs: Math.round(performance.now() - started) });
    } catch (err) {
      console.error("[welcome] demo tool call failed", err);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const finishTour = () => {
    dismissWelcome();
    void navigate({ to: "/" });
  };

  const tokenEstimate = outcome ? tokenEstimateOf(outcome.result) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Welcome to Elliot"
        description="Three moves, sixty seconds: call a real tool, watch the trace it left, then hand the keys to your agent."
        actions={
          <Button variant="ghost" onClick={finishTour}>
            Skip the tour
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <StepBadge number={1} done={outcome !== null} />
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                Run a tool <Wrench className="h-4 w-4 text-muted-foreground" />
              </CardTitle>
              <CardDescription>
                {demoTool
                  ? "The bundled demo connector is already live. This call joins customer and usage data from two sources into one context-sized result."
                  : "No tools are loaded yet — build a connector first, then come back for the rest of the tour."}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {demoTool ? (
            <>
              <Button onClick={() => void runDemoTool()} disabled={isPending}>
                <Play className="mr-2 h-4 w-4" />
                {isPending ? "Running…" : `Run ${demoTool.id}`}
              </Button>
              {error ? (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              ) : null}
              {outcome ? (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{outcome.latencyMs} ms</Badge>
                    {tokenEstimate !== null ? (
                      <Badge variant="secondary">~{tokenEstimate} tokens</Badge>
                    ) : null}
                    <span className="text-xs text-muted-foreground">
                      Small enough to live in an agent&apos;s context window — that&apos;s the
                      point.
                    </span>
                  </div>
                  <pre className="max-h-64 overflow-auto rounded-lg border bg-muted/40 p-3 text-xs">
                    {JSON.stringify(outcome.result, null, 2)}
                  </pre>
                </div>
              ) : null}
            </>
          ) : (
            <Button asChild variant="outline">
              <Link to="/connector">Open the connector editor</Link>
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <StepBadge number={2} done={false} />
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                See the trace <Activity className="h-4 w-4 text-muted-foreground" />
              </CardTitle>
              <CardDescription>
                Every call you just made — arguments, rows, latency, token cost — is already in
                the Agent Console. This is what you&apos;ll see for every agent, every session.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline">
            <Link to="/console">Open the Agent Console</Link>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <StepBadge number={3} done={false} />
            <div className="space-y-1">
              <CardTitle>Connect your agent</CardTitle>
              <CardDescription>
                Point Claude Code, Cursor, Codex, or OpenClaw at this server and the same tools —
                and the same traces — are theirs.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <AgentOnboarding />
          <div className="flex justify-end">
            <Button onClick={finishTour}>Done — take me to the dashboard</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
