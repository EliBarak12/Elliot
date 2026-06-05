import { describe, it, expect } from "vitest";
import { isExpectedNoConnector, redactConnectionConfig } from "@/lib/connection";

describe("isExpectedNoConnector", () => {
  it("treats no-connector / connectivity messages as expected", () => {
    expect(isExpectedNoConnector("No connector built yet")).toBe(true);
    expect(isExpectedNoConnector("RUNTIME_NOT_FOUND")).toBe(true);
    expect(isExpectedNoConnector("Failed to fetch")).toBe(true);
    expect(isExpectedNoConnector("network error")).toBe(true);
  });

  it("treats other messages as real errors", () => {
    expect(isExpectedNoConnector("Invalid SQL in tool")).toBe(false);
    expect(isExpectedNoConnector("permission denied")).toBe(false);
  });
});

describe("redactConnectionConfig", () => {
  it("redacts secret-bearing keys case-insensitively at any depth", () => {
    const input = {
      url: "https://api.example.com",
      api_key: "sk-123",
      nested: { Authorization: "Bearer xyz", keep: "ok" },
      list: [{ password: "p" }, { plain: "v" }],
    };
    expect(redactConnectionConfig(input)).toEqual({
      url: "https://api.example.com",
      api_key: "[REDACTED]",
      nested: { Authorization: "[REDACTED]", keep: "ok" },
      list: [{ password: "[REDACTED]" }, { plain: "v" }],
    });
  });

  it("passes through primitives unchanged", () => {
    expect(redactConnectionConfig("hello")).toBe("hello");
    expect(redactConnectionConfig(42)).toBe(42);
    expect(redactConnectionConfig(null)).toBe(null);
  });
});
