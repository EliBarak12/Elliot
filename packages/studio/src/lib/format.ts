// Display formatting helpers shared across views.

// Render a millisecond duration as a rounded "<n>ms" string, e.g. 42.7 -> "43ms".
export function formatMs(ms: number): string {
  return `${ms.toFixed(0)}ms`;
}
