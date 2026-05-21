import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Radio } from "lucide-react";
import {
  type Harness,
  TRACE_HOOK_QUERY_KEY,
  useToggleTraceHook,
  useTraceHookStatus,
} from "@/hooks/useTraceHook";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const HARNESS_LABELS: Record<Harness, string> = {
  "claude-code": "Claude Code",
  codex: "Codex",
  cursor: "Cursor",
};

export function TraceHookPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useTraceHookStatus();
  const toggle = useToggleTraceHook();
  const harnesses = data?.harnesses ?? [];

  function onToggle(harness: Harness, install: boolean) {
    toggle.mutate(
      { harness, install },
      {
        onSuccess: () => {
          void qc.invalidateQueries({ queryKey: [...TRACE_HOOK_QUERY_KEY] });
          toast.success(
            install
              ? `Trace hook installed for ${HARNESS_LABELS[harness]}. Restart it to start streaming reasoning.`
              : `Trace hook removed for ${HARNESS_LABELS[harness]}.`
          );
        },
        onError: (err) =>
          toast.error(
            err instanceof Error ? err.message : "Could not update the trace hook."
          ),
      }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-muted-foreground" />
          Capture agent reasoning
        </CardTitle>
        <CardDescription>
          Tool calls show up automatically. To also capture the user prompt, the model's
          reasoning, and the final answer from your local agent runs, install the Elliot trace
          hook into your coding agent — then restart it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        )}
        {!isLoading &&
          harnesses.map((h) => (
            <div
              key={h.harness}
              data-testid="trace-hook-row"
              className="flex items-center gap-3 rounded-md border border-border/60 px-3 py-2"
            >
              <span className="text-sm font-medium text-foreground">
                {HARNESS_LABELS[h.harness]}
              </span>
              <Badge variant={h.installed ? "success" : "secondary"} className="text-2xs">
                {h.installed ? "installed" : "off"}
              </Badge>
              <span className="font-mono text-2xs text-muted-foreground truncate hidden sm:inline">
                {h.config_path}
              </span>
              <Button
                size="sm"
                variant={h.installed ? "outline" : "default"}
                disabled={toggle.isPending}
                onClick={() => onToggle(h.harness, !h.installed)}
                className="ml-auto"
              >
                {h.installed ? "Remove" : "Install"}
              </Button>
            </div>
          ))}
        {!isLoading && data?.runtime_url && (
          <p className="text-2xs text-muted-foreground">
            Runs are shipped to <span className="font-mono">{data.runtime_url}/v1/trace/ingest</span>
            . Prefer the terminal? Run{" "}
            <span className="font-mono">elliot trace install --harness claude-code</span>.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
