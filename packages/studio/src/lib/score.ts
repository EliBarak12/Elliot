// Quality-score tiers (0-100), mirroring the readiness scoring shown in the
// Evaluation views: >=90 is good (success), >=60 is acceptable (warning),
// below that needs work (destructive). Centralised so the thresholds and their
// semantic colours stay consistent across every score readout.
export const SCORE_GOOD = 90;
export const SCORE_WARN = 60;

export type ScoreTone = "success" | "warning" | "destructive";

export function scoreTone(score: number): ScoreTone {
  if (score >= SCORE_GOOD) return "success";
  if (score >= SCORE_WARN) return "warning";
  return "destructive";
}

// Semantic colour class for a score with the given utility prefix, e.g.
// scoreToneClass(95, "text") -> "text-success", scoreToneClass(40, "stroke") ->
// "stroke-destructive".
export function scoreToneClass(score: number, prefix: string): string {
  return `${prefix}-${scoreTone(score)}`;
}
