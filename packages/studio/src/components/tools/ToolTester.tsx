import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useCallTool } from "@/hooks/useTools";
import type { ParameterDefinition } from "@/types/api";

interface Props {
  toolId: string;
  parameters: ParameterDefinition[];
}

interface CallResult {
  rows?: unknown[];
  error?: string;
  latency: number;
}

export function ToolTester({ toolId, parameters }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CallResult | null>(null);
  const { mutateAsync: callTool, isPending } = useCallTool();

  const requiredFilled = parameters
    .filter((p) => p.required)
    .every((p) => values[p.name]?.trim());

  const handleRun = async () => {
    const t0 = performance.now();
    try {
      const params: Record<string, unknown> = {};
      for (const p of parameters) {
        const raw = values[p.name];
        if (raw === undefined) continue;
        if (p.type === "integer") {
          // Radix 10 avoids legacy octal parsing; fall back to the raw string
          // when the input isn't a valid number so the backend can report it.
          const n = parseInt(raw, 10);
          params[p.name] = Number.isNaN(n) ? raw : n;
        } else if (p.type === "number") {
          const n = parseFloat(raw);
          params[p.name] = Number.isNaN(n) ? raw : n;
        } else {
          params[p.name] = raw;
        }
      }
      const res = await callTool({ name: "elliot_preview_tool", args: { tool_id: toolId, params } });
      const latency = performance.now() - t0;
      const rows = Array.isArray(res) ? res : (res as { rows?: unknown[] })?.rows;
      setResult({ rows: rows ?? [], latency });
    } catch (err) {
      const latency = performance.now() - t0;
      setResult({ error: err instanceof Error ? err.message : String(err), latency });
    }
  };

  return (
    <div className="space-y-3">
      {parameters.map((p) => (
        <div key={p.name}>
          <label className="text-xs font-medium">
            {p.name}
            {p.required && <span className="text-destructive ml-0.5">*</span>}
          </label>
          <Input
            placeholder={p.type}
            value={values[p.name] ?? ""}
            onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
            className="h-7 text-xs mt-0.5"
          />
        </div>
      ))}

      <Button
        size="sm"
        disabled={!requiredFilled || isPending}
        onClick={() => void handleRun()}
      >
        {isPending ? "Running…" : "Run"}
      </Button>

      {result && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium">Result</span>
            <Badge variant="outline" className="text-xs">
              {result.latency.toFixed(0)}ms
            </Badge>
          </div>
          {result.error ? (
            <p className="text-xs text-destructive">{result.error}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="text-xs w-full border-collapse">
                <thead>
                  {result.rows && result.rows.length > 0 && (
                    <tr>
                      {typeof result.rows[0] === "object" && result.rows[0] !== null ? (
                        Object.keys(result.rows[0] as object).map((k) => (
                          <th key={k} className="border px-2 py-1 text-left bg-muted font-medium">
                            {k}
                          </th>
                        ))
                      ) : (
                        <th className="border px-2 py-1 text-left bg-muted font-medium">value</th>
                      )}
                    </tr>
                  )}
                </thead>
                <tbody>
                  {(result.rows ?? []).map((row, i) => (
                    <tr key={i}>
                      {typeof row === "object" && row !== null ? (
                        Object.values(row as object).map((v, j) => (
                          <td key={j} className="border px-2 py-1">
                            {String(v)}
                          </td>
                        ))
                      ) : (
                        <td className="border px-2 py-1">{String(row)}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.rows?.length === 0 && (
                <p className="text-xs text-muted-foreground py-2">No rows returned.</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
