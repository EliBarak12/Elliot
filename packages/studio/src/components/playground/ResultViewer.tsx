import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface Props {
  result: unknown;
  latencyMs: number;
}

function getRowCount(result: unknown): number | null {
  if (Array.isArray(result)) return result.length;
  if (result && typeof result === "object") {
    const r = result as Record<string, unknown>;
    if (Array.isArray(r.rows)) return r.rows.length;
    if (typeof r.row_count === "number") return r.row_count;
  }
  return null;
}

function syntaxHighlight(json: string): string {
  return json
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
      (match) => {
        let cls = "text-green-400";
        if (/^"/.test(match)) cls = match.endsWith(":") ? "text-blue-400" : "text-yellow-300";
        else if (/true|false/.test(match)) cls = "text-purple-400";
        else if (/null/.test(match)) cls = "text-gray-400";
        return `<span class="${cls}">${match}</span>`;
      }
    );
}

export function ResultViewer({ result, latencyMs }: Props) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(result, null, 2);
  const rowCount = getRowCount(result);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Badge variant="outline" className="text-xs">
          {latencyMs.toFixed(0)}ms
        </Badge>
        {rowCount !== null && (
          <Badge variant="secondary" className="text-xs">
            {rowCount} rows
          </Badge>
        )}
        <Button size="sm" variant="ghost" className="h-6 text-xs ml-auto" onClick={() => void handleCopy()}>
          {copied ? "Copied!" : "Copy"}
        </Button>
      </div>
      <pre
        className="text-xs bg-slate-900 text-slate-100 rounded-md p-4 overflow-auto max-h-96"
        dangerouslySetInnerHTML={{ __html: syntaxHighlight(json) }}
      />
    </div>
  );
}
