/** Shapes and helpers for the Elliot runtime's tool-result envelope:
 * structuredContent = {rows, count, estimated_tokens, truncated?, ...}. */

export type Row = Record<string, unknown>;

export interface ToolData {
  rows: Row[];
  count: number;
  truncated: boolean;
  truncationNote: string | null;
  empty: boolean;
  emptyNote: string | null;
  /** Raw text of the first text content block (markdown preset input). */
  text: string | null;
}

export function parseToolResult(params: {
  content?: unknown;
  structuredContent?: unknown;
}): ToolData {
  const structured = (params.structuredContent ?? {}) as Record<string, unknown>;
  let rows: Row[] = [];
  const rawRows = structured["rows"];
  if (Array.isArray(rawRows)) {
    rows = rawRows.filter((r): r is Row => typeof r === "object" && r !== null);
  }
  let text: string | null = null;
  if (Array.isArray(params.content)) {
    const first = params.content.find(
      (c): c is { type: string; text: string } =>
        typeof c === "object" && c !== null && (c as { type?: unknown }).type === "text"
    );
    text = first?.text ?? null;
  }
  return {
    rows,
    count: typeof structured["count"] === "number" ? structured["count"] : rows.length,
    truncated: structured["truncated"] === true,
    truncationNote:
      typeof structured["truncation_note"] === "string" ? structured["truncation_note"] : null,
    empty: structured["empty"] === true,
    emptyNote: typeof structured["empty_note"] === "string" ? structured["empty_note"] : null,
    text,
  };
}

/** Pick the preset for "auto": rows → table (or detail for a single record);
 * no rows but text → markdown. */
export function resolveAutoPreset(data: ToolData): "table" | "detail" | "markdown" {
  if (data.rows.length === 1 && Object.keys(data.rows[0]).length > 1) return "detail";
  if (data.rows.length > 0) return "table";
  return data.text ? "markdown" : "table";
}

export function inferColumns(rows: Row[], cap = 8): string[] {
  const seen: string[] = [];
  for (const row of rows.slice(0, 25)) {
    for (const key of Object.keys(row)) {
      if (!seen.includes(key)) seen.push(key);
    }
  }
  return seen.slice(0, cap);
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function prettyLabel(field: string): string {
  return field.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
