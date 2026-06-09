import { describe, it, expect } from "vitest";
import { SCORE_GOOD, SCORE_WARN, scoreTone, scoreToneClass } from "@/lib/score";

describe("scoreTone", () => {
  it("maps score bands to semantic tones", () => {
    expect(scoreTone(SCORE_GOOD)).toBe("success");
    expect(scoreTone(100)).toBe("success");
    expect(scoreTone(SCORE_WARN)).toBe("warning");
    expect(scoreTone(SCORE_GOOD - 1)).toBe("warning");
    expect(scoreTone(SCORE_WARN - 1)).toBe("destructive");
    expect(scoreTone(0)).toBe("destructive");
  });
});

describe("scoreToneClass", () => {
  it("prefixes the tone for text/stroke utilities", () => {
    expect(scoreToneClass(95, "text")).toBe("text-success");
    expect(scoreToneClass(70, "stroke")).toBe("stroke-warning");
    expect(scoreToneClass(30, "text")).toBe("text-destructive");
  });
});
