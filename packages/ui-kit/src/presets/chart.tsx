import { useMemo, useState } from "react";
import type { PresetProps } from "../AppShell";
import { mappingList } from "../lib/config";
import { cn, formatCell, prettyLabel, type Row } from "../lib/data";

/** Chart preset: single numeric series → bars, several series → lines.
 *
 * Hand-rolled SVG rather than a chart library — the whole view ships as one
 * self-contained document, so every dependency is paid on every render of
 * every tool. Colors come from the host/brand CSS variables so the chart
 * follows the connector's accent and the host theme automatically.
 */

const WIDTH = 640;
const HEIGHT = 240;
const PAD = { top: 14, right: 16, bottom: 34, left: 48 };
const MAX_SERIES = 4;
const MAX_X_LABELS = 8;

// Series 1 is the brand accent; the rest are derived from it so a multi-line
// chart stays on-brand without the author picking a palette.
const SERIES_COLORS = [
  "var(--primary)",
  "color-mix(in srgb, var(--primary) 55%, var(--foreground))",
  "color-mix(in srgb, var(--primary) 30%, var(--muted-foreground))",
  "var(--muted-foreground)",
];

interface ChartShape {
  xField: string;
  yFields: string[];
  points: Array<{ label: string; row: Row; values: Array<number | null> }>;
  min: number;
  max: number;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** mapping.x / mapping.y first; otherwise first non-numeric field labels the
 * axis and every numeric field becomes a series (capped). */
function resolveShape(rows: Row[], mapping: Record<string, string>): ChartShape | null {
  if (rows.length === 0) return null;
  const keys = Object.keys(rows[0]);
  const numeric = keys.filter((k) => rows.some((r) => isFiniteNumber(r[k])));
  const mappedX = mappingList(mapping["x"])[0];
  const mappedY = mappingList(mapping["y"]).filter((f) => numeric.includes(f));
  const xField = mappedX && keys.includes(mappedX) ? mappedX : keys.find((k) => !numeric.includes(k));
  const yFields = (mappedY.length > 0 ? mappedY : numeric.filter((k) => k !== xField)).slice(
    0,
    MAX_SERIES
  );
  if (yFields.length === 0) return null;
  const points = rows.map((row, i) => ({
    label: xField ? formatCell(row[xField]) : String(i + 1),
    row,
    values: yFields.map((f) => (isFiniteNumber(row[f]) ? row[f] : null)),
  }));
  const values = points.flatMap((p) => p.values).filter(isFiniteNumber);
  if (values.length === 0) return null;
  const min = Math.min(0, ...values);
  const max = Math.max(...values, min + 1e-9);
  return { xField: xField ?? "#", yFields, points, min, max };
}

/** 4-step "nice" value axis. */
function ticks(min: number, max: number): number[] {
  const span = max - min;
  const step = span / 4;
  return [0, 1, 2, 3, 4].map((i) => min + step * i);
}

function compact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(0)}k`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function ChartPreset({ config, data, onContext }: PresetProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const shape = useMemo(() => resolveShape(data.rows, config.mapping), [data.rows, config.mapping]);

  if (!shape) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        {data.emptyNote ?? "No numeric fields to chart."}
      </p>
    );
  }

  const { xField, yFields, points, min, max } = shape;
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const xStep = plotW / Math.max(points.length, 1);
  const yPos = (v: number) => PAD.top + plotH - ((v - min) / (max - min)) * plotH;
  const mode: "bars" | "lines" = yFields.length === 1 ? "bars" : "lines";
  const labelEvery = Math.max(1, Math.ceil(points.length / MAX_X_LABELS));

  function selectPoint(index: number) {
    setSelected(index);
    const point = points[index];
    onContext(
      `In the ${config.title} chart the user selected ${xField}=${point.label}: ${JSON.stringify(point.row)}`,
      { selected_point: point.row }
    );
  }

  return (
    <div className="p-4">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={`${prettyLabel(yFields.join(", "))} by ${prettyLabel(xField)}`}
      >
        {ticks(min, max).map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yPos(t)}
              y2={yPos(t)}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 6}
              y={yPos(t) + 3}
              textAnchor="end"
              fontSize={10}
              fill="var(--muted-foreground)"
            >
              {compact(t)}
            </text>
          </g>
        ))}

        {mode === "bars" &&
          points.map((point, i) => {
            const value = point.values[0];
            if (value === null) return null;
            const barW = Math.min(xStep * 0.6, 48);
            const x = PAD.left + xStep * i + (xStep - barW) / 2;
            const y0 = yPos(Math.max(0, min));
            const y1 = yPos(value);
            return (
              <rect
                key={i}
                x={x}
                y={Math.min(y0, y1)}
                width={barW}
                height={Math.max(Math.abs(y0 - y1), 1)}
                rx={2}
                fill="var(--primary)"
                opacity={selected === null || selected === i ? 1 : 0.35}
                className="cursor-pointer transition-opacity"
                onClick={() => selectPoint(i)}
              >
                <title>{`${point.label}: ${formatCell(value)}`}</title>
              </rect>
            );
          })}

        {mode === "lines" &&
          yFields.map((field, s) => {
            const path = points
              .map((point, i) => {
                const value = point.values[s];
                if (value === null) return null;
                const x = PAD.left + xStep * i + xStep / 2;
                return `${x},${yPos(value)}`;
              })
              .filter(Boolean);
            return (
              <g key={field}>
                <polyline
                  points={path.join(" ")}
                  fill="none"
                  stroke={SERIES_COLORS[s]}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {points.map((point, i) => {
                  const value = point.values[s];
                  if (value === null) return null;
                  return (
                    <circle
                      key={i}
                      cx={PAD.left + xStep * i + xStep / 2}
                      cy={yPos(value)}
                      r={selected === i ? 4.5 : 3}
                      fill={SERIES_COLORS[s]}
                      className="cursor-pointer"
                      onClick={() => selectPoint(i)}
                    >
                      <title>{`${point.label} · ${prettyLabel(field)}: ${formatCell(value)}`}</title>
                    </circle>
                  );
                })}
              </g>
            );
          })}

        {points.map((point, i) =>
          i % labelEvery === 0 ? (
            <text
              key={i}
              x={PAD.left + xStep * i + xStep / 2}
              y={HEIGHT - PAD.bottom + 14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--muted-foreground)"
            >
              {point.label.length > 10 ? `${point.label.slice(0, 9)}…` : point.label}
            </text>
          ) : null
        )}
      </svg>

      {yFields.length > 1 && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          {yFields.map((field, s) => (
            <span key={field} className="flex items-center gap-1.5 text-2xs text-muted-foreground">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: SERIES_COLORS[s] }}
              />
              {prettyLabel(field)}
            </span>
          ))}
        </div>
      )}
      <p className={cn("mt-1 text-2xs text-muted-foreground", selected === null && "opacity-60")}>
        {selected === null
          ? "Click a data point to send it to the model as context."
          : `Selected ${xField}=${points[selected].label} — sent to the model.`}
      </p>
    </div>
  );
}
