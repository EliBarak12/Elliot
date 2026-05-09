import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useTools, useCallTool } from "@/hooks/useTools";
import { ParameterForm } from "@/components/playground/ParameterForm";
import { ResultViewer } from "@/components/playground/ResultViewer";
import type { ToolDefinition } from "@/types/api";

interface Invocation {
  toolId: string;
  params: Record<string, string>;
  result: unknown;
  latencyMs: number;
  timestamp: number;
}

export default function PlaygroundPage() {
  const { data: toolsRaw } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];
  const { mutateAsync: callTool, isPending } = useCallTool();

  const [selectedToolId, setSelectedToolId] = useState<string>("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<Invocation[]>([]);
  const [currentResult, setCurrentResult] = useState<{ result: unknown; latencyMs: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedTool = tools.find((t) => t.id === selectedToolId) ?? null;

  const handleToolChange = (id: string) => {
    setSelectedToolId(id);
    setParams({});
    setCurrentResult(null);
    setError(null);
  };

  const requiredFilled =
    selectedTool?.parameters
      .filter((p) => p.required)
      .every((p) => params[p.name]?.trim()) ?? false;

  const handleRun = async () => {
    if (!selectedTool) return;
    setError(null);
    const t0 = performance.now();
    try {
      const args: Record<string, unknown> = {};
      for (const p of selectedTool.parameters) {
        if (params[p.name] !== undefined) {
          args[p.name] =
            p.type === "integer"
              ? parseInt(params[p.name])
              : p.type === "number"
                ? parseFloat(params[p.name])
                : p.type === "boolean"
                  ? params[p.name] === "true"
                  : params[p.name];
        }
      }
      const result = await callTool({ name: selectedTool.id, args });
      const latencyMs = performance.now() - t0;
      setCurrentResult({ result, latencyMs });
      setHistory((prev) => [
        { toolId: selectedTool.id, params: { ...params }, result, latencyMs, timestamp: Date.now() },
        ...prev,
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleExportFixture = () => {
    if (!currentResult || !selectedTool) return;
    const fixture = {
      tool_id: selectedTool.id,
      params,
      expected_result: currentResult.result,
      timestamp: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(fixture, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedTool.id}-fixture.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const loadFromHistory = (inv: Invocation) => {
    setSelectedToolId(inv.toolId);
    setParams(inv.params);
    setCurrentResult({ result: inv.result, latencyMs: inv.latencyMs });
  };

  return (
    <div className="flex gap-4 h-full">
      <div className="flex flex-col gap-4 w-80 shrink-0">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Tool Invoker</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground">Select tool</label>
              <select
                value={selectedToolId}
                onChange={(e) => handleToolChange(e.target.value)}
                className="block w-full h-8 text-sm border rounded px-2 mt-1"
              >
                <option value="">— choose a tool —</option>
                {tools.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>

            {selectedTool && (
              <>
                <ParameterForm
                  parameters={selectedTool.parameters}
                  values={params}
                  onChange={setParams}
                />
                {error && <p className="text-xs text-destructive">{error}</p>}
                <Button
                  size="sm"
                  className="w-full"
                  disabled={!requiredFilled || isPending}
                  onClick={() => void handleRun()}
                >
                  {isPending ? "Running…" : "Run"}
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-col gap-4 flex-1 overflow-hidden">
        {currentResult && (
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">Result</CardTitle>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleExportFixture}>
                  Export as fixture
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <ResultViewer result={currentResult.result} latencyMs={currentResult.latencyMs} />
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">History</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 overflow-y-auto max-h-64">
            {history.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                No invocations yet. Select a tool and run it.
              </p>
            )}
            {history.map((inv, i) => (
                <button
                  key={i}
                  className="w-full text-left text-xs flex items-center gap-2 hover:bg-accent rounded px-2 py-1"
                  onClick={() => loadFromHistory(inv)}
                >
                  <span className="font-medium">{inv.toolId}</span>
                  <Badge variant="outline" className="text-xs ml-auto shrink-0">
                    {inv.latencyMs.toFixed(0)}ms
                  </Badge>
                  <span className="text-muted-foreground text-xs">
                    {new Date(inv.timestamp).toLocaleTimeString()}
                  </span>
                </button>
              ))}
            </CardContent>
          </Card>
      </div>
    </div>
  );
}
