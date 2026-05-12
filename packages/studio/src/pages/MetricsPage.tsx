import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertCircle, BarChart3, Gauge, RefreshCw, Timer } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { StatCard } from "@/components/ui/stat-card";
import { useMetrics } from "@/hooks/useMetrics";
import { cn } from "@/lib/utils";

interface ToolMetric {
  tool_id: string;
  call_count: number;
  error_rate: number;
  avg_latency_ms: number;
}

interface MetricsResponse {
  metrics: ToolMetric[];
  days: number;
}

interface TokenEfficiencyRow {
  tool_id: string;
  call_count: number;
  avg_tokens: number;
  max_tokens: number;
  avg_duration_ms: number;
  error_count: number;
  risk: "low" | "medium" | "high";
  suggestion: string | null;
}

interface TokenEfficiencyResponse {
  tools: TokenEfficiencyRow[];
}

function tokenRiskVariant(risk: TokenEfficiencyRow["risk"]) {
  if (risk === "high") return "destructive";
  if (risk === "medium") return "warning";
  return "success";
}

function TokenBar({ avg, max }: { avg: number; max: number }) {
  const barMax = Math.max(max, 1);
  const avgPct = Math.min((avg / barMax) * 100, 100);
  const tone = avg > 1000 ? "bg-destructive" : avg > 300 ? "bg-warning" : "bg-success";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500 ease-apple", tone)}
          style={{ width: `${avgPct}%` }}
        />
      </div>
      <span className="text-2xs tabular-nums text-muted-foreground w-16 text-right">
        {avg.toFixed(0)}/{max.toFixed(0)}
      </span>
    </div>
  );
}

const DATE_RANGES = [7, 14, 30, 90] as const;

function CallBar({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="space-y-2">
      {data.slice(0, 10).map((item) => (
        <div key={item.label} className="flex items-center gap-3">
          <span className="font-mono text-2xs truncate w-40 text-right text-muted-foreground">
            {item.label}
          </span>
          <div className="flex-1 h-5 bg-muted/60 rounded-md overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary/80 to-primary rounded-md transition-all duration-500 ease-apple"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          <span className="text-xs tabular-nums w-12 text-right font-medium">
            {item.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function MetricsPage() {
  const [days, setDays] = useState(30);
  const queryClient = useQueryClient();
  const { data: metricsRaw, isLoading } = useMetrics(days);
  const metricsData = metricsRaw as MetricsResponse | undefined;
  const metrics = metricsData?.metrics ?? [];

  const { data: efficiencyRaw } = useQuery<TokenEfficiencyResponse>({
    queryKey: ["token-efficiency"],
    queryFn: async () => {
      const r = await fetch("http://localhost:3001/v1/metrics/token-efficiency");
      if (!r.ok) throw new Error("Failed to fetch token efficiency");
      return r.json() as Promise<TokenEfficiencyResponse>;
    },
    refetchInterval: 30_000,
  });
  const efficiencyTools = efficiencyRaw?.tools ?? [];

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["metrics"] });
  };

  const totalCalls = metrics.reduce((sum, m) => sum + m.call_count, 0);
  const avgErrorRate =
    metrics.reduce((sum, m) => sum + m.error_rate, 0) / (metrics.length || 1);
  const avgLatency =
    metrics.reduce((sum, m) => sum + m.avg_latency_ms, 0) / (metrics.length || 1);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Metrics"
        description="Tool performance, error rates, and token efficiency across your connector."
        actions={
          <div className="flex items-center gap-2">
            <div className="inline-flex items-center gap-0.5 rounded-md bg-muted p-0.5">
              {DATE_RANGES.map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={cn(
                    "px-2.5 h-7 text-xs font-medium rounded transition-all",
                    days === d
                      ? "bg-background shadow-sm text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {d}d
                </button>
              ))}
            </div>
            <Button size="sm" variant="outline" onClick={handleRefresh} className="gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        }
      />

      {isLoading && (
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      )}

      {!isLoading && metrics.length === 0 && (
        <EmptyState
          icon={BarChart3}
          title="No audit data yet"
          description="Run some tools from the Playground to start populating metrics."
        />
      )}

      {!isLoading && metrics.length > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <StatCard
              label="Total calls"
              value={totalCalls.toLocaleString()}
              icon={Activity}
              tone="primary"
              hint={`Past ${days} days`}
            />
            <StatCard
              label="Error rate"
              value={`${(avgErrorRate * 100).toFixed(1)}%`}
              icon={AlertCircle}
              tone={avgErrorRate > 0.05 ? "destructive" : "success"}
              hint="Average across tools"
            />
            <StatCard
              label="Avg latency"
              value={`${avgLatency.toFixed(0)}ms`}
              icon={Timer}
              tone={avgLatency > 500 ? "warning" : "default"}
              hint="Across all tools"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Top tools by call count</CardTitle>
              <CardDescription>The most-invoked tools over the selected window.</CardDescription>
            </CardHeader>
            <CardContent>
              <CallBar data={metrics.map((m) => ({ label: m.tool_id, value: m.call_count }))} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tool performance</CardTitle>
              <CardDescription>Per-tool calls, success rate, and latency.</CardDescription>
            </CardHeader>
            <CardContent className="px-0 pb-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="text-left py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                        Tool
                      </th>
                      <th className="text-right py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                        Calls
                      </th>
                      <th className="text-right py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                        Success
                      </th>
                      <th className="text-right py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                        Avg latency
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.map((m) => (
                      <tr
                        key={m.tool_id}
                        className="border-b border-border/40 last:border-0 hover:bg-muted/30"
                      >
                        <td className="py-2.5 px-5 text-xs font-mono">{m.tool_id}</td>
                        <td className="text-right py-2.5 px-5 text-xs tabular-nums">
                          {m.call_count.toLocaleString()}
                        </td>
                        <td className="text-right py-2.5 px-5">
                          <Badge
                            variant={m.error_rate > 0.1 ? "destructive" : "success"}
                            className="tabular-nums"
                          >
                            {((1 - m.error_rate) * 100).toFixed(1)}%
                          </Badge>
                        </td>
                        <td className="text-right py-2.5 px-5 text-xs tabular-nums">
                          {m.avg_latency_ms.toFixed(0)}ms
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {efficiencyTools.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <CardTitle className="flex items-center gap-2">
                  <Gauge className="h-4 w-4 text-primary" />
                  Token efficiency
                </CardTitle>
                <CardDescription>
                  Tools that return large payloads are flagged for context-window optimization.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60">
                    <th className="text-left py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                      Tool
                    </th>
                    <th className="text-left py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground w-56">
                      Avg / max tokens
                    </th>
                    <th className="text-center py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                      Risk
                    </th>
                    <th className="text-left py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
                      Suggestion
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {efficiencyTools.map((row) => (
                    <tr
                      key={row.tool_id}
                      className="border-b border-border/40 last:border-0 hover:bg-muted/30"
                    >
                      <td className="py-3 px-5 text-xs font-mono">{row.tool_id}</td>
                      <td className="py-3 px-5">
                        <TokenBar avg={row.avg_tokens} max={row.max_tokens} />
                      </td>
                      <td className="text-center py-3 px-5">
                        <Badge variant={tokenRiskVariant(row.risk)}>{row.risk}</Badge>
                      </td>
                      <td className="py-3 px-5 text-xs text-muted-foreground">
                        {row.suggestion ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
