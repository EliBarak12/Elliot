import { describe, it, expect } from "vitest";
import {
  TOKEN_RISK_HIGH,
  TOKEN_RISK_MEDIUM,
  tokenRiskLevel,
  tokenToneClass,
} from "@/lib/tokenRisk";

describe("tokenRiskLevel", () => {
  it("classifies above the high threshold as high", () => {
    expect(tokenRiskLevel(TOKEN_RISK_HIGH + 1)).toBe("high");
    expect(tokenRiskLevel(5000)).toBe("high");
  });

  it("classifies the medium band as medium", () => {
    expect(tokenRiskLevel(TOKEN_RISK_MEDIUM + 1)).toBe("medium");
    expect(tokenRiskLevel(TOKEN_RISK_HIGH)).toBe("medium");
  });

  it("classifies the low band as low", () => {
    expect(tokenRiskLevel(0)).toBe("low");
    expect(tokenRiskLevel(TOKEN_RISK_MEDIUM)).toBe("low");
  });
});

describe("tokenToneClass", () => {
  it("defaults to the text prefix", () => {
    expect(tokenToneClass(2000)).toBe("text-destructive");
    expect(tokenToneClass(500)).toBe("text-warning");
    expect(tokenToneClass(10)).toBe("text-success");
  });

  it("supports the bg prefix", () => {
    expect(tokenToneClass(2000, "bg")).toBe("bg-destructive");
    expect(tokenToneClass(500, "bg")).toBe("bg-warning");
    expect(tokenToneClass(10, "bg")).toBe("bg-success");
  });
});
