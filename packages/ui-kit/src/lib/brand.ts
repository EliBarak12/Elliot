import type { ElliotBranding } from "./config";

/** Applies the connector's design system to the document.
 *
 * Runs on load and on every host-context change (a theme toggle in the host
 * flips light/dark). Brand tokens are written as inline custom properties on
 * :root, which outrank both the stylesheet fallbacks and the host's
 * variables; anything the brand does not set keeps deferring to the host. */

const RADIUS: Record<string, string> = {
  none: "0px",
  sm: "0.25rem",
  md: "0.5rem",
  lg: "0.75rem",
  xl: "1rem",
};

// Density scales the root font size (the browser default is 16px); every
// spacing and type utility is in rem, so the whole view tightens or loosens
// together. "comfortable" is the unscaled default.
const DENSITY: Record<string, string> = {
  compact: "15px",
  comfortable: "",
  spacious: "17px",
};

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

function rgb(hex: string): [number, number, number] | null {
  if (!HEX.test(hex)) return null;
  const h = hex.length === 4 ? hex.slice(1).replace(/./g, (c) => c + c) : hex.slice(1);
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** WCAG relative luminance, 0 (black) … 1 (white). */
export function luminance(hex: string): number | null {
  const c = rgb(hex);
  if (!c) return null;
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Near-black or white, whichever reads better on `bg`. */
export function readableOn(bg: string): string {
  const l = luminance(bg);
  if (l === null) return "#ffffff";
  // Contrast against white vs. against near-black (#111318, L≈0.0065).
  const vsWhite = 1.05 / (l + 0.05);
  const vsDark = (l + 0.05) / 0.0565;
  return vsDark > vsWhite ? "#111318" : "#ffffff";
}

let fontLinked: string | null = null;

export function applyBrand(theme: "light" | "dark" | undefined, b?: ElliotBranding | null): void {
  const root = document.documentElement;
  const set = (name: string, value: string | null | undefined) => {
    if (value) root.style.setProperty(name, value);
    else root.style.removeProperty(name);
  };
  const dark = theme === "dark";
  const accent = dark ? (b?.accent_dark ?? b?.accent) : b?.accent;
  set("--primary", accent);
  set("--primary-foreground", accent ? (b?.accent_foreground ?? readableOn(accent)) : null);

  const bg = dark ? b?.background_dark : b?.background;
  const fg = dark ? b?.foreground_dark : b?.foreground;
  set("--background", bg);
  set("--card", bg);
  set("--foreground", fg);
  if (bg && fg) {
    // Derive the quieter surfaces from the pair so the palette stays coherent.
    set("--muted", `color-mix(in srgb, ${fg} 6%, ${bg})`);
    set("--border", `color-mix(in srgb, ${fg} 14%, ${bg})`);
    set("--muted-foreground", `color-mix(in srgb, ${fg} 62%, ${bg})`);
  } else {
    set("--muted", null);
    set("--border", null);
    set("--muted-foreground", null);
  }

  set("--radius", b?.radius ? RADIUS[b.radius] : null);
  root.style.fontSize = b?.density ? DENSITY[b.density] : "";

  if (b?.font_family) {
    if (b.font_url && fontLinked !== b.font_url && b.font_url.startsWith("https://")) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = b.font_url;
      document.head.appendChild(link);
      fontLinked = b.font_url;
    }
    // The family name is validated server-side to letters, digits, spaces,
    // '-' and '_', so it cannot break out of the declaration.
    document.body.style.fontFamily = `"${b.font_family}", var(--font-sans, ui-sans-serif, system-ui, sans-serif)`;
  } else {
    document.body.style.fontFamily = "";
  }
}
