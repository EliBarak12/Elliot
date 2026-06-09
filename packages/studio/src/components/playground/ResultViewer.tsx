import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatMs } from "@/lib/format";

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

// Token-based JSON highlighter. Returns a tokenised JSX tree — never
// dangerouslySetInnerHTML — so connector-supplied result values cannot
// become a stored-XSS vector even if the escape logic regresses.
type Token = { text: string; cls: string };

function tokenize(json: string): Token[] {
  const tokens: Token[] = [];
  const re =
    /("(?:\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"\s*:?)|(\btrue\b|\bfalse\b)|(\bnull\b)|(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(json)) !== null) {
    if (m.index > last) tokens.push({ text: json.slice(last, m.index), cls: "" });
    const match = m[0];
    let cls = "text-green-400";
    if (m[1]) cls = match.endsWith(":") ? "text-blue-400" : "text-yellow-300";
    else if (m[2]) cls = "text-purple-400";
    else if (m[3]) cls = "text-gray-400";
    tokens.push({ text: match, cls });
    last = re.lastIndex;
  }
  if (last < json.length) tokens.push({ text: json.slice(last), cls: "" });
  return tokens;
}

export function ResultViewer({ result, latencyMs }: Props) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const json = JSON.stringify(result, null, 2);
  const rowCount = getRowCount(result);
  const tokens = tokenize(json);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setCopyFailed(false);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      // navigator.clipboard fails on insecure origins, in iframes without
      // permission, or when the page isn't focused. Surface the failure
      // instead of silently lying that it succeeded.
      console.warn("[result-viewer] copy failed", err);
      setCopyFailed(true);
      setTimeout(() => setCopyFailed(false), 2000);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Badge variant="outline" className="text-xs">
          {formatMs(latencyMs)}
        </Badge>
        {rowCount !== null && (
          <Badge variant="secondary" className="text-xs">
            {rowCount} rows
          </Badge>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="h-6 text-xs ml-auto"
          onClick={() => void handleCopy()}
        >
          {copied ? "Copied!" : copyFailed ? "Copy failed" : "Copy"}
        </Button>
      </div>
      <pre className="text-xs bg-slate-900 text-slate-100 rounded-md p-4 overflow-auto max-h-96">
        {tokens.map((t, i) =>
          t.cls ? (
            <span key={i} className={t.cls}>
              {t.text}
            </span>
          ) : (
            t.text
          )
        )}
      </pre>
    </div>
  );
}
