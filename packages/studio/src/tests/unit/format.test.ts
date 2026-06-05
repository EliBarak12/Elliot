import { describe, it, expect } from "vitest";
import { formatMs } from "@/lib/format";

describe("formatMs", () => {
  it("rounds to whole milliseconds and appends the unit", () => {
    expect(formatMs(42.7)).toBe("43ms");
    expect(formatMs(42.2)).toBe("42ms");
    expect(formatMs(0)).toBe("0ms");
    expect(formatMs(1000)).toBe("1000ms");
  });
});
