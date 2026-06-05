import { describe, it, expect } from "vitest";
import { severityBadgeVariant } from "@/lib/severity";

describe("severityBadgeVariant", () => {
  it("maps high to destructive and medium to warning", () => {
    expect(severityBadgeVariant("high", "secondary")).toBe("destructive");
    expect(severityBadgeVariant("medium", "secondary")).toBe("warning");
  });

  it("returns the caller's fallback for anything else", () => {
    expect(severityBadgeVariant("low", "success")).toBe("success");
    expect(severityBadgeVariant("info", "secondary")).toBe("secondary");
    expect(severityBadgeVariant("", "secondary")).toBe("secondary");
  });
});
