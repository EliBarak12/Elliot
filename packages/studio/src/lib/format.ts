// Display formatting helpers shared across views.

// Render a millisecond duration as a rounded "<n>ms" string, e.g. 42.7 -> "43ms".
export function formatMs(ms: number): string {
  return `${ms.toFixed(0)}ms`;
}

// Render a 0-1 ratio as a percentage string, e.g. 0.024 -> "2.4%".
export function formatPercent(ratio: number, fractionDigits = 1): string {
  return `${(ratio * 100).toFixed(fractionDigits)}%`;
}
