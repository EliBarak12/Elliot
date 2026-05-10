import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { callTool } from "@/lib/mcp-client";

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

type Tab = "suites" | "quality";

function ScoreGauge({ score }: { score: number }) {
  const color = score >= 90 ? "text-green-600" : score >= 60 ? "text-yellow-600" : "text-red-600";
  return (
    <div className="flex flex-col items-center py-4">
      <span className={`text-5xl font-bold ${color}`}>{score.toFixed(1)}</span>
      <span className="text-xs text-muted-foreground mt-1">/ 100</span>
    </div>
  );
}

function CaseTable({ cases }: { cases: EvalCaseResult[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b">
          <th className="text-left py-1 text-xs font-medium text-muted-foreground">Case</th>
          <th className="text-left py-1 text-xs font-medium text-muted-foreground">Tool</th>
          <th className="text-right py-1 text-xs font-medium text-muted-foreground">Result</th>
          <th className="text-right py-1 text-xs font-medium text-muted-foreground">Latency</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => (
          <tr key={c.case_id} className="border-b last:border-0">
            <td className="py-1 text-xs font-mono">{c.case_id}</td>
            <td className="py-1 text-xs font-mono">{c.tool_id}</td>
            <td className="text-right py-1">
              {c.error ? (
                <Badge variant="destructive" className="text-xs" title={c.error}>
                  error
                </Badge>
              ) : c.passed ? (
                <Badge variant="secondary" className="text-xs bg-green-100 text-green-800">
                  pass
                </Badge>
              ) : (
                <Badge variant="destructive" className="text-xs">
                  fail
                </Badge>
              )}
            </td>
            <td className="text-right py-1 text-xs">{c.latency_ms.toFixed(0)}ms</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EvalSuitesTab() {
  const [suiteId, setSuiteId] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<EvalRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prevScore, setPrevScore] = useState<number | null>(null);

  const regressions =
    result && prevScore !== null
      ? result.cases.filter((c) => !c.passed).length
      : 0;

  const handleRun = async () => {
    if (!suiteId.trim()) return;
    setRunning(true);
    setError(null);
    try {
      const prev = result;
      if (prev) setPrevScore(prev.score);
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
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Run Eval Suite</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={suiteId}
              onChange={(e) => setSuiteId(e.target.value)}
              placeholder="suite-id (e.g. smoke)"
              className="h-8 text-sm flex-1"
            />
            <Button
              size="sm"
              disabled={!suiteId.trim() || running}
              onClick={() => void handleRun()}
            >
              {running ? "Running…" : "Run"}
            </Button>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">Results — {result.suite_id}</CardTitle>
              <div className="flex gap-2 items-center">
                {regressions > 0 && (
                  <Badge variant="destructive" className="text-xs">
                    {regressions} regression{regressions > 1 ? "s" : ""}
                  </Badge>
                )}
                <Badge variant="outline" className="text-xs">
                  {result.passed} / {result.passed + result.failed} passed
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <ScoreGauge score={result.score} />
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
      <div className="flex items-center gap-3">
        <Button size="sm" disabled={scanning} onClick={() => void handleScan()}>
          {scanning ? "Scanning…" : "Run Scan"}
        </Button>
        {result && (
          <div className="flex gap-2">
            <Badge variant="outline" className="text-xs">
              Score: {result.overall_score.toFixed(1)}
            </Badge>
            {result.error_count > 0 && (
              <Badge variant="destructive" className="text-xs">
                {result.error_count} error{result.error_count > 1 ? "s" : ""}
              </Badge>
            )}
            {result.warning_count > 0 && (
              <Badge variant="secondary" className="text-xs bg-yellow-100 text-yellow-800">
                {result.warning_count} warning{result.warning_count > 1 ? "s" : ""}
              </Badge>
            )}
          </div>
        )}
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {result && (
        <div className="space-y-3">
          {result.tool_scores.map((ts) => (
            <Card key={ts.tool_id}>
              <CardHeader className="pb-1">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-xs font-mono">{ts.tool_id}</CardTitle>
                  <Badge
                    variant={ts.score >= 90 ? "secondary" : "destructive"}
                    className={`text-xs ${ts.score >= 90 ? "bg-green-100 text-green-800" : ""}`}
                  >
                    {ts.score.toFixed(0)}
                  </Badge>
                </div>
              </CardHeader>
              {ts.issues.length > 0 && (
                <CardContent className="pt-0">
                  <ul className="space-y-1">
                    {ts.issues.map((issue, i) => (
                      <li key={i} className="flex gap-2 text-xs">
                        <Badge
                          variant={issue.severity === "error" ? "destructive" : "outline"}
                          className="text-xs shrink-0"
                        >
                          {issue.severity}
                        </Badge>
                        <span className="text-muted-foreground">{issue.message}</span>
                      </li>
                    ))}
                  </ul>
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
  const [tab, setTab] = useState<Tab>("suites");

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b pb-2">
        <Button
          size="sm"
          variant={tab === "suites" ? "default" : "ghost"}
          className="h-7 text-xs"
          onClick={() => setTab("suites")}
        >
          Eval Suites
        </Button>
        <Button
          size="sm"
          variant={tab === "quality" ? "default" : "ghost"}
          className="h-7 text-xs"
          onClick={() => setTab("quality")}
        >
          Quality Scan
        </Button>
      </div>

      {tab === "suites" ? <EvalSuitesTab /> : <QualityScanTab />}
    </div>
  );
}
