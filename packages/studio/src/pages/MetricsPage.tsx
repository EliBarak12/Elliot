import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useMetrics } from "@/hooks/useMetrics";

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

function tokenRiskBadge(risk: TokenEfficiencyRow["risk"]) {
  if (risk === "high") return <Badge variant="destructive" className="text-xs">high</Badge>;
  if (risk === "medium") return <Badge variant="outline" className="text-xs text-yellow-700 border-yellow-400">medium</Badge>;
  return <Badge variant="secondary" className="text-xs text-green-700">low</Badge>;
}

function TokenBar({ avg, max }: { avg: number; max: number }) {
  const barMax = Math.max(max, 1);
  const avgPct = Math.min((avg / barMax) * 100, 100);
  const color = avg > 1000 ? "bg-red-500" : avg > 300 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-3 bg-muted rounded overflow-hidden">
        <div className={`h-full rounded ${color}`} style={{ width: `${avgPct}%` }} />
      </div>
      <span className="text-xs w-14 text-right text-muted-foreground">
        {avg.toFixed(0)}/{max.toFixed(0)}
      </span>
    </div>
  );
}

const DATE_RANGES = [7, 14, 30, 90] as const;

function BarChart({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="space-y-1">
      {data.slice(0, 10).map((item) => (
        <div key={item.label} className="flex items-center gap-2">
          <span className="text-xs w-36 truncate text-right">{item.label}</span>
          <div className="flex-1 h-5 bg-muted rounded overflow-hidden">
            <div
              className="h-full bg-primary rounded"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          <span className="text-xs w-8 text-right">{item.value}</span>
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

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading metrics…</p>;

  if (metrics.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-muted-foreground">No audit data yet.</p>
        <p className="text-sm text-muted-foreground">
          Run some tools from the{" "}
          <a href="/playground" className="underline hover:text-foreground">
            Playground
          </a>{" "}
          to see metrics here.
        </p>
      </div>
    );
  }

  const totalCalls = metrics.reduce((sum, m) => sum + m.call_count, 0);
  const avgErrorRate =
    metrics.reduce((sum, m) => sum + m.error_rate, 0) / (metrics.length || 1);
  const avgLatency =
    metrics.reduce((sum, m) => sum + m.avg_latency_ms, 0) / (metrics.length || 1);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex gap-1">
          {DATE_RANGES.map((d) => (
            <Button
              key={d}
              size="sm"
              variant={days === d ? "default" : "outline"}
              className="h-7 text-xs"
              onClick={() => setDays(d)}
            >
              {d}d
            </Button>
          ))}
        </div>
        <Button size="sm" variant="ghost" className="h-7 text-xs ml-auto" onClick={handleRefresh}>
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground">Total calls</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{totalCalls}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground">Avg error rate</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{(avgErrorRate * 100).toFixed(1)}%</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground">Avg latency</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{avgLatency.toFixed(0)}ms</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Top tools by call count</CardTitle>
        </CardHeader>
        <CardContent>
          <BarChart
            data={metrics.map((m) => ({ label: m.tool_id, value: m.call_count }))}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Tool performance</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-1 text-xs font-medium text-muted-foreground">Tool</th>
                <th className="text-right py-1 text-xs font-medium text-muted-foreground">Calls</th>
                <th className="text-right py-1 text-xs font-medium text-muted-foreground">
                  Success rate
                </th>
                <th className="text-right py-1 text-xs font-medium text-muted-foreground">
                  Avg latency
                </th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.tool_id} className="border-b last:border-0">
                  <td className="py-1 text-xs font-mono">{m.tool_id}</td>
                  <td className="text-right py-1 text-xs">{m.call_count}</td>
                  <td className="text-right py-1 text-xs">
                    <Badge
                      variant={m.error_rate > 0.1 ? "destructive" : "secondary"}
                      className="text-xs"
                    >
                      {((1 - m.error_rate) * 100).toFixed(1)}%
                    </Badge>
                  </td>
                  <td className="text-right py-1 text-xs">{m.avg_latency_ms.toFixed(0)}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {efficiencyTools.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Token efficiency</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-1 text-xs font-medium text-muted-foreground">Tool</th>
                  <th className="text-left py-1 text-xs font-medium text-muted-foreground w-40">
                    Avg / Max tokens
                  </th>
                  <th className="text-right py-1 text-xs font-medium text-muted-foreground">Risk</th>
                  <th className="text-left py-1 text-xs font-medium text-muted-foreground pl-3">
                    Suggestion
                  </th>
                </tr>
              </thead>
              <tbody>
                {efficiencyTools.map((row) => (
                  <tr key={row.tool_id} className="border-b last:border-0">
                    <td className="py-1.5 text-xs font-mono pr-3">{row.tool_id}</td>
                    <td className="py-1.5 w-48">
                      <TokenBar avg={row.avg_tokens} max={row.max_tokens} />
                    </td>
                    <td className="text-right py-1.5 pl-3">{tokenRiskBadge(row.risk)}</td>
                    <td className="py-1.5 text-xs text-muted-foreground pl-3">
                      {row.suggestion ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
