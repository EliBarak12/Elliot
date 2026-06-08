// Badge variant for a "high" / "medium" / lower severity or risk level. The
// high -> destructive, medium -> warning convention is shared across the
// Metrics and Agent Console views; only the fallback for lower levels differs
// (e.g. "success" for token risk, "secondary" for session signals), so callers
// pass it in. The generic keeps the fallback's literal type so the result is
// still assignable to the Badge `variant` prop.
export function severityBadgeVariant<T extends string>(
  severity: string,
  fallback: T
): "destructive" | "warning" | T {
  if (severity === "high") return "destructive";
  if (severity === "medium") return "warning";
  return fallback;
}
