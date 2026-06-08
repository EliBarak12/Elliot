// Pure helpers for the connector connection view.

// Config keys whose values must never be shown in the UI.
export const SECRET_FIELDS = new Set([
  "api_key",
  "bearer_token",
  "token",
  "password",
  "secret",
  "authorization",
  "auth",
]);

// On a fresh session the plugin may not be reachable yet, or no connector has
// been built — both are expected and should not raise a user-facing error.
export function isExpectedNoConnector(message: string): boolean {
  const m = message.toLowerCase();
  return (
    m.includes("no connector") ||
    m.includes("not connected") ||
    m.includes("not_found") ||
    m.includes("connection") ||
    m.includes("fetch") ||
    m.includes("network")
  );
}

// Deep-copy a connection config with any secret-bearing field replaced by
// "[REDACTED]" so credentials never reach the rendered DOM.
export function redactConnectionConfig(config: unknown): unknown {
  if (Array.isArray(config)) {
    return config.map((item) => redactConnectionConfig(item));
  }
  if (config !== null && typeof config === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(config as Record<string, unknown>)) {
      out[key] = SECRET_FIELDS.has(key.toLowerCase())
        ? "[REDACTED]"
        : redactConnectionConfig(value);
    }
    return out;
  }
  return config;
}
