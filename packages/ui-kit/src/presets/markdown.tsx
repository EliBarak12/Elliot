import { useMemo } from "react";
import type { PresetProps } from "../AppShell";

/** Minimal, dependency-free markdown rendering for text results: headings,
 * bold/italic/code, bullet lists, fenced code blocks. Everything is built
 * from escaped text — never raw HTML from the tool result. */
export function MarkdownPreset({ data }: PresetProps) {
  const blocks = useMemo(() => parseBlocks(data.text ?? ""), [data.text]);
  if (!data.text) {
    return <p className="p-4 text-sm text-muted-foreground">No text content.</p>;
  }
  return <div className="p-4 space-y-2 text-sm leading-relaxed">{blocks}</div>;
}

function inline(text: string, key: number): React.ReactNode {
  // Split on `code`, **bold**, *italic* — escaped by construction since we
  // only ever emit text nodes.
  const parts: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      parts.push(
        <code key={`${key}-${i++}`} className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("**")) {
      parts.push(<strong key={`${key}-${i++}`}>{token.slice(2, -2)}</strong>);
    } else {
      parts.push(<em key={`${key}-${i++}`}>{token.slice(1, -1)}</em>);
    }
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function parseBlocks(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const lines = text.split("\n");
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      out.push(
        <pre
          key={key++}
          className="overflow-x-auto rounded-lg border border-border bg-muted p-3 font-mono text-xs"
        >
          {code.join("\n")}
        </pre>
      );
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const cls =
        level === 1
          ? "text-base font-semibold"
          : level === 2
            ? "text-sm font-semibold"
            : "text-sm font-medium";
      out.push(
        <p key={key++} className={cls}>
          {inline(heading[2], key)}
        </p>
      );
      i += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      out.push(
        <ul key={key++} className="list-disc space-y-1 pl-5">
          {items.map((item, j) => (
            <li key={j}>{inline(item, key * 100 + j)}</li>
          ))}
        </ul>
      );
      continue;
    }
    if (line.trim()) {
      out.push(<p key={key++}>{inline(line, key)}</p>);
    }
    i += 1;
  }
  return out;
}
