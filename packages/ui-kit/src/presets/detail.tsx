import { useMemo } from "react";
import type { PresetProps } from "../AppShell";
import { mappingList } from "../lib/config";
import { formatCell, prettyLabel } from "../lib/data";

/** Single-record card: label/value grid over the first row. */
export function DetailPreset({ config, data }: PresetProps) {
  const row = data.rows[0];
  const fields = useMemo(() => {
    if (!row) return [];
    const mapped = mappingList(config.mapping["fields"]);
    const keys = mapped.length > 0 ? mapped.filter((f) => f in row) : Object.keys(row);
    return keys;
  }, [config.mapping, row]);

  if (!row) {
    return (
      <p className="p-4 text-sm text-muted-foreground">{data.emptyNote ?? "Nothing found."}</p>
    );
  }

  return (
    <dl className="grid grid-cols-[max-content,1fr] gap-x-6 gap-y-2 p-4 text-sm">
      {fields.map((field) => (
        <div key={field} className="contents">
          <dt className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground self-center">
            {prettyLabel(field)}
          </dt>
          <dd className="break-words">{formatCell(row[field])}</dd>
        </div>
      ))}
    </dl>
  );
}
