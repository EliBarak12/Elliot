import { useMemo } from "react";
import type { PresetProps } from "../AppShell";
import { mappingList } from "../lib/config";
import { formatCell, prettyLabel } from "../lib/data";

/** Stat-card grid: big numbers from the first row's numeric fields (or the
 * ones named in mapping.value_fields). */
export function MetricPreset({ config, data }: PresetProps) {
  const row = data.rows[0] ?? {};
  const fields = useMemo(() => {
    const mapped = mappingList(config.mapping["value_fields"]);
    if (mapped.length > 0) return mapped.filter((f) => f in row);
    return Object.keys(row).filter((k) => typeof row[k] === "number");
  }, [config.mapping, row]);

  if (fields.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        {data.emptyNote ?? "No numeric fields to display."}
      </p>
    );
  }

  return (
    <div className="grid gap-3 p-4 [grid-template-columns:repeat(auto-fit,minmax(9rem,1fr))]">
      {fields.map((field) => (
        <div key={field} className="rounded-lg border border-border bg-card px-4 py-3">
          <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
            {prettyLabel(field)}
          </p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{formatCell(row[field])}</p>
        </div>
      ))}
    </div>
  );
}
