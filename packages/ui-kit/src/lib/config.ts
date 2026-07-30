/** The per-tool configuration elliot_core.apps.template_builder injects into
 * the `#elliot-ui-config` script tag of the served ui:// document. */
export interface ElliotUiConfig {
  tool_id: string;
  title: string;
  preset: "auto" | "table" | "detail" | "metric" | "chart" | "form" | "markdown" | "custom";
  /** Preset-specific field wiring, e.g. {columns: "id,name"} — see ToolUIConfig. */
  mapping: Record<string, string>;
  category: "READ" | "WRITE" | "ACTION";
}

const FALLBACK: ElliotUiConfig = {
  tool_id: "unknown",
  title: "Tool result",
  preset: "auto",
  mapping: {},
  category: "READ",
};

export function readConfig(): ElliotUiConfig {
  const el = document.getElementById("elliot-ui-config");
  if (!el?.textContent) {
    console.warn("[ui-kit] no #elliot-ui-config found; using fallback");
    return FALLBACK;
  }
  try {
    const parsed: unknown = JSON.parse(el.textContent);
    if (typeof parsed !== "object" || parsed === null) return FALLBACK;
    return { ...FALLBACK, ...(parsed as Partial<ElliotUiConfig>) };
  } catch (err) {
    console.error("[ui-kit] failed to parse #elliot-ui-config", err);
    return FALLBACK;
  }
}

/** Split a comma-separated mapping value into trimmed, non-empty names. */
export function mappingList(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}
