// Token-count risk thresholds, mirroring the runtime's token-efficiency
// buckets (see /v1/metrics/token-efficiency): a result over 1000 estimated
// tokens is "high", over 300 is "medium". Centralised so the Metrics and
// Agent Console views can't drift from each other — or from the backend.
export const TOKEN_RISK_HIGH = 1000;
export const TOKEN_RISK_MEDIUM = 300;

export type TokenRisk = "high" | "medium" | "low";

export function tokenRiskLevel(tokens: number): TokenRisk {
  if (tokens > TOKEN_RISK_HIGH) return "high";
  if (tokens > TOKEN_RISK_MEDIUM) return "medium";
  return "low";
}

// Map a token count to a semantic colour class with the given utility prefix,
// e.g. tokenToneClass(1200) -> "text-destructive", tokenToneClass(50, "bg") ->
// "bg-success".
export function tokenToneClass(tokens: number, prefix: "text" | "bg" = "text"): string {
  const level = tokenRiskLevel(tokens);
  const suffix = level === "high" ? "destructive" : level === "medium" ? "warning" : "success";
  return `${prefix}-${suffix}`;
}
