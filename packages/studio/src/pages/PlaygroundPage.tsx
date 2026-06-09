import { useState } from 'react';
import { Download, FlaskConical, History, Play } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { formatMs } from '@/lib/format';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useTools, useCallTool } from '@/hooks/useTools';
import { ParameterForm } from '@/components/playground/ParameterForm';
import { ResultViewer } from '@/components/playground/ResultViewer';
import type { ToolDefinition } from '@/types/api';
import { cn } from '@/lib/utils';

interface Invocation {
  id: string;
  toolId: string;
  params: Record<string, string>;
  result: unknown;
  latencyMs: number;
  timestamp: number;
}

// Cap history so a long playground session doesn't grow memory / the DOM list
// without bound.
const MAX_HISTORY = 50;

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function PlaygroundPage() {
  const { data: toolsRaw } = useTools();
  const tools = Array.isArray(toolsRaw) ? (toolsRaw as ToolDefinition[]) : [];
  const { mutateAsync: callTool, isPending } = useCallTool();

  const [selectedToolId, setSelectedToolId] = useState<string>('');
  const [params, setParams] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<Invocation[]>([]);
  const [currentResult, setCurrentResult] = useState<{
    result: unknown;
    latencyMs: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedTool = tools.find((t) => t.id === selectedToolId) ?? null;

  const handleToolChange = (id: string) => {
    setSelectedToolId(id);
    setParams({});
    setCurrentResult(null);
    setError(null);
  };

  const requiredFilled =
    selectedTool?.parameters.filter((p) => p.required).every((p) => params[p.name]?.trim()) ??
    false;

  const handleRun = async () => {
    if (!selectedTool) return;
    setError(null);
    const t0 = performance.now();
    try {
      const args: Record<string, unknown> = {};
      for (const p of selectedTool.parameters) {
        const raw = params[p.name];
        if (raw === undefined) continue;
        if (p.type === 'integer') {
          // Radix 10 avoids legacy octal parsing; fall back to the raw string
          // when the input isn't a valid number so the backend can report it.
          const n = parseInt(raw, 10);
          args[p.name] = Number.isNaN(n) ? raw : n;
        } else if (p.type === 'number') {
          const n = parseFloat(raw);
          args[p.name] = Number.isNaN(n) ? raw : n;
        } else if (p.type === 'boolean') {
          args[p.name] = raw === 'true';
        } else {
          args[p.name] = raw;
        }
      }
      // User-defined connector tools are not exposed as MCP tools by the plugin;
      // invoke them through the meta-tool 'elliot_preview_tool' which executes
      // the registered SQL against the session's SQLite engine.
      const result = await callTool({
        name: 'elliot_preview_tool',
        args: { tool_id: selectedTool.id, params: args },
      });
      const latencyMs = performance.now() - t0;
      setCurrentResult({ result, latencyMs });
      setHistory((prev) =>
        [
          {
            id: newId(),
            toolId: selectedTool.id,
            params: { ...params },
            result,
            latencyMs,
            timestamp: Date.now(),
          },
          ...prev,
        ].slice(0, MAX_HISTORY),
      );
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
    const blob = new Blob([JSON.stringify(fixture, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
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
    <div className="space-y-6 flex flex-col h-full">
      <PageHeader
        title="Playground"
        description="Invoke any tool with custom parameters, inspect the result, and export it as an eval fixture."
      />

      <div className="flex gap-4 flex-1 min-h-0">
        <div className="flex flex-col gap-4 w-80 shrink-0 overflow-y-auto scrollbar-thin pr-1">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FlaskConical className="h-4 w-4 text-primary" />
                Invoker
              </CardTitle>
              <CardDescription>Pick a tool, fill the params, run it.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label>Tool</Label>
                <Select value={selectedToolId} onValueChange={handleToolChange}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose a tool" />
                  </SelectTrigger>
                  <SelectContent>
                    {tools.map((t) => (
                      <SelectItem key={t.id} value={t.id}>
                        <span className="flex items-center gap-2">
                          <span>{t.name}</span>
                          <Badge variant="muted" className="ml-auto">
                            {t.category}
                          </Badge>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {selectedTool && (
                <>
                  <ParameterForm
                    parameters={selectedTool.parameters}
                    values={params}
                    onChange={setParams}
                  />
                  {error && (
                    <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                      {error}
                    </div>
                  )}
                  <Button
                    className="w-full gap-1.5"
                    disabled={!requiredFilled || isPending}
                    onClick={() => void handleRun()}
                  >
                    <Play className="h-3.5 w-3.5" />
                    {isPending ? 'Running…' : 'Run tool'}
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card className="flex-1 min-h-0">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-4 w-4 text-muted-foreground" />
                History
              </CardTitle>
            </CardHeader>
            <CardContent className="px-2 pb-2">
              {history.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6">
                  Run a tool to populate history.
                </p>
              ) : (
                <div className="space-y-0.5 max-h-72 overflow-y-auto scrollbar-thin">
                  {history.map((inv) => (
                    <button
                      key={inv.id}
                      className="w-full flex items-center gap-2 px-2 py-1.5 text-left rounded-md hover:bg-muted/40 transition-colors"
                      onClick={() => loadFromHistory(inv)}
                    >
                      <span
                        className={cn(
                          'h-1.5 w-1.5 rounded-full shrink-0',
                          inv.result !== undefined ? 'bg-success' : 'bg-muted-foreground',
                        )}
                      />
                      <span className="text-xs font-medium truncate flex-1 min-w-0">
                        {inv.toolId}
                      </span>
                      <span className="text-2xs text-muted-foreground tabular-nums">
                        {formatMs(inv.latencyMs)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-4 flex-1 overflow-y-auto scrollbar-thin min-w-0">
          {currentResult ? (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between gap-3">
                  <div className="space-y-1">
                    <CardTitle>Result</CardTitle>
                    <CardDescription className="flex items-center gap-2">
                      <Badge variant="muted" className="tabular-nums">
                        {formatMs(currentResult.latencyMs)}
                      </Badge>
                      <span>{selectedTool?.name}</span>
                    </CardDescription>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleExportFixture}
                    className="gap-1.5"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Export fixture
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <ResultViewer result={currentResult.result} latencyMs={currentResult.latencyMs} />
              </CardContent>
            </Card>
          ) : (
            <EmptyState
              icon={FlaskConical}
              title="No result yet"
              description={
                selectedTool
                  ? 'Fill the parameters and run the tool to see the result.'
                  : 'Select a tool from the invoker on the left to get started.'
              }
              className="m-auto w-full max-w-md"
            />
          )}
        </div>
      </div>
    </div>
  );
}
