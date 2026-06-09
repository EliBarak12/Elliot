import { describe, it, expect } from "vitest";
import { formatMs, formatPercent } from "@/lib/format";

describe("formatMs", () => {
  it("rounds to whole milliseconds and appends the unit", () => {
    expect(formatMs(42.7)).toBe("43ms");
    expect(formatMs(42.2)).toBe("42ms");
    expect(formatMs(0)).toBe("0ms");
    expect(formatMs(1000)).toBe("1000ms");
  });
});

describe("formatPercent", () => {
  it("scales a 0-1 ratio to a percentage with one decimal by default", () => {
    expect(formatPercent(0.024)).toBe("2.4%");
    expect(formatPercent(1)).toBe("100.0%");
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("honors a custom fraction-digit count", () => {
    expect(formatPercent(0.5, 0)).toBe("50%");
  });
});
