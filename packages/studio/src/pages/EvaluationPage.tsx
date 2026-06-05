import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardCheck,
  Play,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMs } from "@/lib/format";
import { callTool } from "@/lib/mcp-client";
import { cn } from "@/lib/utils";

interface EvalCaseResult {
  case_id: string;
  tool_id: string;
  passed: boolean;
  actual_rows: unknown[];
  latency_ms: number;
  error: string | null;
}

interface EvalRunResult {
  suite_id: string;
  run_at: string;
  score: number;
  passed: number;
  failed: number;
  cases: EvalCaseResult[];
}

interface EvalSuite {
  suite_id: string;
  path: string;
  format: string;
}

interface EvalSuiteListEnvelope {
  suites?: EvalSuite[];
  count?: number;
  eval_dir?: string;
}

// Sentinel value for the "custom suite ID" option in the suite dropdown. Radix
// Select forbids an empty-string item value, so use a non-suite_id token.
const CUSTOM_SUITE_VALUE = "__custom__";

interface ToolIssue {
  check: string;
  severity: string;
  message: string;
}

interface ToolScore {
  tool_id: string;
  score: number;
  issues: ToolIssue[];
}

interface QualityScanResult {
  overall_score: number;
  error_count: number;
  warning_count: number;
  last_eval_score: number | null;
  tool_scores: ToolScore[];
}

function ScoreRing({ score }: { score: number }) {
  const tone =
    score >= 90 ? "text-success" : score >= 60 ? "text-warning" : "text-destructive";
  const ringTone =
    score >= 90 ? "stroke-success" : score >= 60 ? "stroke-warning" : "stroke-destructive";
  const circumference = 2 * Math.PI * 44;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className="relative flex items-center justify-center">
      <svg className="w-28 h-28 -rotate-90" viewBox="0 0 100 100">
        <circle
          cx="50"
          cy="50"
          r="44"
          fill="none"
          className="stroke-muted"
          strokeWidth="6"
        />
        <circle
          cx="50"
          cy="50"
          r="44"
          fill="none"
          className={cn("transition-all duration-700 ease-apple", ringTone)}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-2xl font-semibold tabular-nums tracking-tight", tone)}>
          {score.toFixed(0)}
        </span>
        <span className="text-2xs text-muted-foreground">/ 100</span>
      </div>
    </div>
  );
}

function CaseTable({ cases }: { cases: EvalCaseResult[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60">
            <th className="text-left py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
              Case
            </th>
            <th className="text-left py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
              Tool
            </th>
            <th className="text-center py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
              Result
            </th>
            <th className="text-right py-2 px-5 text-2xs font-medium uppercase tracking-wider text-muted-foreground">
              Latency
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr
              key={c.case_id}
              className="border-b border-border/40 last:border-0 hover:bg-muted/30"
            >
              <td className="py-2.5 px-5 text-xs font-mono">{c.case_id}</td>
              <td className="py-2.5 px-5 text-xs font-mono text-muted-foreground">{c.tool_id}</td>
              <td className="text-center py-2.5 px-5">
                {c.error ? (
                  <Badge variant="destructive" title={c.error} className="gap-1">
                    <XCircle className="h-3 w-3" />
                    error
                  </Badge>
                ) : c.passed ? (
                  <Badge variant="success" className="gap-1">
                    <CheckCircle2 className="h-3 w-3" />
                    pass
                  </Badge>
                ) : (
                  <Badge variant="destructive" className="gap-1">
                    <XCircle className="h-3 w-3" />
                    fail
                  </Badge>
                )}
              </td>
              <td className="text-right py-2.5 px-5 text-xs tabular-nums">
                {formatMs(c.latency_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvalSuitesTab() {
  const [suiteId, setSuiteId] = useState("");
  // When true, the user is typing a suite_id by hand instead of picking one
  // from the discovered list (custom / fallback path).
  const [customMode, setCustomMode] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<EvalRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const {
    data: suites,
    isLoading: suitesLoading,
    isError: suitesError,
  } = useQuery({
    queryKey: ["eval-suites"],
    queryFn: async () => {
      const raw = (await callTool("elliot_list_eval_suites", {})) as
        | EvalSuiteListEnvelope
        | EvalSuite[];
      // The MCP tool returns { suites: [...], count, eval_dir }. Unwrap to a
      // plain array so the dropdown can map over it without re-checking shape.
      if (Array.isArray(raw)) return raw;
      return Array.isArray(raw?.suites) ? raw.suites : [];
    },
    // Live-refresh so suites the agent adds appear without a page reload.
    refetchInterval: 30_000,
  });

  // Force the manual text field whenever discovery yields nothing usable, so
  // the user is never left without a way to enter a suite ID.
  const hasSuites = (suites?.length ?? 0) > 0;
  const useCustomField = customMode || !hasSuites;

  // Value shown in the Select: the matching suite, or the custom sentinel.
  const selectValue =
    !useCustomField && suites?.some((s) => s.suite_id === suiteId)
      ? suiteId
      : CUSTOM_SUITE_VALUE;

  const handleSelect = (value: string) => {
    if (value === CUSTOM_SUITE_VALUE) {
      setCustomMode(true);
      setSuiteId("");
      return;
    }
    setCustomMode(false);
    setSuiteId(value);
  };

  const handleRun = async () => {
    if (!suiteId.trim()) return;
    setRunning(true);
    setError(null);
    try {
      const res = await callTool("elliot_run_eval", { suite_id: suiteId.trim() });
      setResult(res as EvalRunResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Run an eval suite</CardTitle>
          <CardDescription>
            Execute a suite of test cases against your connector and see pass/fail per case.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2 items-end">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="suite-id">Suite ID</Label>
              {hasSuites && (
                <Select value={selectValue} onValueChange={handleSelect}>
                  <SelectTrigger id="suite-id" className="font-mono">
                    <SelectValue placeholder="Select a suite" />
                  </SelectTrigger>
                  <SelectContent>
                    {suites?.map((s) => (
                      <SelectItem key={s.suite_id} value={s.suite_id} className="font-mono">
                        {s.suite_id}
                      </SelectItem>
                    ))}
                    <SelectItem value={CUSTOM_SUITE_VALUE}>Other / custom…</SelectItem>
                  </SelectContent>
                </Select>
              )}
              {useCustomField && (
                <Input
                  id={hasSuites ? "suite-id-custom" : "suite-id"}
                  value={suiteId}
                  onChange={(e) => setSuiteId(e.target.value)}
                  placeholder="e.g. smoke"
                  className="font-mono"
                />
              )}
              {suitesError && (
                <p className="text-2xs text-muted-foreground">
                  Could not list suites — enter a suite ID manually.
                </p>
              )}
            </div>
            <Button
              disabled={!suiteId.trim() || running || suitesLoading}
              onClick={() => void handleRun()}
              className="gap-1.5"
            >
              <Play className="h-3.5 w-3.5" />
              {running ? "Running…" : "Run"}
            </Button>
          </div>
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-4">
              <div className="space-y-1">
                <CardTitle className="font-mono">{result.suite_id}</CardTitle>
                <CardDescription>
                  Ran at {new Date(result.run_at).toLocaleString()}
                </CardDescription>
              </div>
              <div className="flex items-center gap-3">
                <Badge
                  variant={result.failed === 0 ? "success" : "destructive"}
                  className="tabular-nums"
                >
                  {result.passed} / {result.passed + result.failed} passed
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-6 pb-4 border-b border-border/60">
              <ScoreRing score={result.score} />
              <div className="space-y-1">
                <p className="text-2xs uppercase tracking-wider text-muted-foreground">Score</p>
                <p className="text-sm text-muted-foreground">
                  <span className="font-medium text-foreground tabular-nums">
                    {result.passed}
                  </span>{" "}
                  passed,{" "}
                  <span className="font-medium text-foreground tabular-nums">{result.failed}</span>{" "}
                  failed across {result.cases.length} cases.
                </p>
              </div>
            </div>
          </CardContent>
          <CardContent className="px-0 pb-0">
            <CaseTable cases={result.cases} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function QualityScanTab() {
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<QualityScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleScan = async () => {
    setScanning(true);
    setError(null);
    try {
      const res = await callTool("elliot_quality_scan", {});
      setResult(res as QualityScanResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-primary" />
                Quality scan
              </CardTitle>
              <CardDescription>
                Scan every tool for description, parameter, and contract quality.
              </CardDescription>
            </div>
            <Button disabled={scanning} onClick={() => void handleScan()} className="gap-1.5">
              <Play className="h-3.5 w-3.5" />
              {scanning ? "Scanning…" : "Run scan"}
            </Button>
          </div>
        </CardHeader>
        {result && (
          <CardContent>
            <div className="flex items-center gap-6 pb-4 border-b border-border/60">
              <ScoreRing score={result.overall_score} />
              <div className="flex gap-2 flex-wrap">
                {result.error_count > 0 && (
                  <Badge variant="destructive" className="gap-1">
                    <AlertCircle className="h-3 w-3" />
                    {result.error_count} {result.error_count === 1 ? "error" : "errors"}
                  </Badge>
                )}
                {result.warning_count > 0 && (
                  <Badge variant="warning">
                    {result.warning_count}{" "}
                    {result.warning_count === 1 ? "warning" : "warnings"}
                  </Badge>
                )}
                {result.error_count === 0 && result.warning_count === 0 && (
                  <Badge variant="success" className="gap-1">
                    <CheckCircle2 className="h-3 w-3" />
                    All checks passed
                  </Badge>
                )}
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          {result.tool_scores.map((ts) => (
            <Card key={ts.tool_id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between gap-3">
                  <CardTitle className="font-mono text-sm">{ts.tool_id}</CardTitle>
                  <Badge
                    variant={ts.score >= 90 ? "success" : ts.score >= 60 ? "warning" : "destructive"}
                    className="tabular-nums"
                  >
                    {ts.score.toFixed(0)} / 100
                  </Badge>
                </div>
              </CardHeader>
              {ts.issues.length > 0 && (
                <CardContent>
                  <div className="space-y-2">
                    {ts.issues.map((issue, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2"
                      >
                        <Badge
                          variant={issue.severity === "error" ? "destructive" : "warning"}
                          className="shrink-0"
                        >
                          {issue.severity}
                        </Badge>
                        <p className="text-xs text-muted-foreground">{issue.message}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EvaluationPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Evaluation"
        description="Run eval suites against your connector and scan tool quality before deploy."
        actions={
          <Badge variant="muted" className="gap-1.5">
            <ClipboardCheck className="h-3 w-3" />
            Quality gate
          </Badge>
        }
      />

      <Tabs defaultValue="suites">
        <TabsList>
          <TabsTrigger value="suites">Eval suites</TabsTrigger>
          <TabsTrigger value="quality">Quality scan</TabsTrigger>
        </TabsList>
        <TabsContent value="suites">
          <EvalSuitesTab />
        </TabsContent>
        <TabsContent value="quality">
          <QualityScanTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
