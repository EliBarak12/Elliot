/** The connector's design system (ConnectorBranding on the Python side).
 * Every token is optional; unset tokens defer to the host theme. */
export interface ElliotBranding {
  /** Brand name shown beside the logo in the view header. */
  name?: string | null;
  /** Hex accent for buttons, highlights, selection and focus. */
  accent?: string | null;
  /** Accent override on dark host themes; falls back to `accent`. */
  accent_dark?: string | null;
  /** Text on the accent; derived from the accent's luminance when unset. */
  accent_foreground?: string | null;
  /** Brand surfaces — unset keeps the host's background and text. */
  background?: string | null;
  foreground?: string | null;
  background_dark?: string | null;
  foreground_dark?: string | null;
  /** Font family name, optionally loaded from `font_url`. */
  font_family?: string | null;
  font_url?: string | null;
  radius?: "none" | "sm" | "md" | "lg" | "xl" | null;
  density?: "compact" | "comfortable" | "spacious" | null;
  /** data:image/... URI or https URL rendered in the view header. */
  logo?: string | null;
}

/** The per-tool configuration elliot_core.apps.template_builder injects into
 * the `#elliot-ui-config` script tag of the served ui:// document. */
export interface ElliotUiConfig {
  tool_id: string;
  title: string;
  preset:
    | "auto"
    | "table"
    | "cards"
    | "detail"
    | "metric"
    | "chart"
    | "form"
    | "markdown"
    | "custom";
  /** Preset-specific field wiring, e.g. {columns: "id,name"} — see ToolUIConfig. */
  mapping: Record<string, string>;
  category: "READ" | "WRITE" | "ACTION";
  branding?: ElliotBranding | null;
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
