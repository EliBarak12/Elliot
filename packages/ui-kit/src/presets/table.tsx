import { useMemo, useState } from "react";
import type { PresetProps } from "../AppShell";
import { mappingList } from "../lib/config";
import { cn, formatCell, inferColumns, prettyLabel, type Row } from "../lib/data";

type SortDir = "asc" | "desc";

/** Sortable, filterable data table — the workhorse preset for READ tools. */
export function TablePreset({ config, data, onContext }: PresetProps) {
  const [filter, setFilter] = useState("");
  const [sortField, setSortField] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [selected, setSelected] = useState<number | null>(null);

  const columns = useMemo(() => {
    const mapped = mappingList(config.mapping["columns"]);
    return mapped.length > 0 ? mapped : inferColumns(data.rows);
  }, [config.mapping, data.rows]);

  const rows = useMemo(() => {
    let out = data.rows;
    if (filter.trim()) {
      const needle = filter.trim().toLowerCase();
      out = out.filter((row) =>
        columns.some((c) => formatCell(row[c]).toLowerCase().includes(needle))
      );
    }
    if (sortField) {
      const dir = sortDir === "asc" ? 1 : -1;
      out = [...out].sort((a, b) => {
        const av = a[sortField];
        const bv = b[sortField];
        if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
        return formatCell(av).localeCompare(formatCell(bv)) * dir;
      });
    }
    return out;
  }, [data.rows, filter, sortField, sortDir, columns]);

  function toggleSort(field: string) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  function selectRow(index: number, row: Row) {
    setSelected(index);
    onContext(
      `In the ${config.title} view the user selected this row: ${JSON.stringify(row)}`,
      { selected_row: row }
    );
  }

  if (data.rows.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        {data.emptyNote ?? "No rows matched."}
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2 px-4 py-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter rows…"
          aria-label="Filter rows"
          className="h-7 w-48 rounded border border-border bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
        />
        <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
          {rows.length} of {data.count} row{data.count === 1 ? "" : "s"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-y border-border bg-muted/60">
              {columns.map((col) => (
                <th key={col} className="p-0 text-left font-medium">
                  <button
                    onClick={() => toggleSort(col)}
                    className="w-full px-3 py-1.5 text-left hover:bg-muted transition-colors"
                  >
                    {prettyLabel(col)}
                    {sortField === col && (
                      <span className="ml-1 text-muted-foreground">
                        {sortDir === "asc" ? "↑" : "↓"}
                      </span>
                    )}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={i}
                onClick={() => selectRow(i, row)}
                className={cn(
                  "border-b border-border/60 border-l-2 border-l-transparent cursor-pointer transition-colors hover:bg-muted/40",
                  selected === i && "bg-muted/70 border-l-primary"
                )}
              >
                {columns.map((col) => (
                  <td key={col} className="px-3 py-1.5 whitespace-nowrap max-w-[16rem] truncate">
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
