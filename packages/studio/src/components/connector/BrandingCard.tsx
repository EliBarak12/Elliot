import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Palette, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { callTool } from "@/lib/mcp-client";
import type { ConnectorBranding } from "@/types/api";

// Mirrors the linter's UI_BRANDING_LOGO_TOO_LARGE threshold: the logo is
// inlined into every tool's view document, so keep it a header-mark size.
const LOGO_WARN_BYTES = 64 * 1024;

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** <input type="color"> only accepts #rrggbb — expand #rgb, fall back on invalid. */
function toColorInputValue(hex: string, fallback: string): string {
  if (!HEX_RE.test(hex)) return fallback;
  if (hex.length === 4) {
    const [r, g, b] = hex.slice(1);
    return `#${r}${r}${g}${g}${b}${b}`;
  }
  return hex;
}

function ColorField({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (next: string) => void;
}) {
  const invalid = value !== "" && !HEX_RE.test(value);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} picker`}
          value={toColorInputValue(value, "#888888")}
          onChange={(e) => onChange(e.target.value)}
          className="h-8 w-9 shrink-0 cursor-pointer rounded border border-border bg-transparent p-0.5"
        />
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value.trim())}
          placeholder="#c02434"
          className="h-8 font-mono text-sm"
        />
        {value && (
          <button
            type="button"
            aria-label={`Clear ${label.toLowerCase()}`}
            onClick={() => onChange("")}
            className="shrink-0 rounded p-1 opacity-60 hover:opacity-100 hover:bg-muted"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <p className={invalid ? "text-2xs text-destructive" : "text-2xs text-muted-foreground"}>
        {invalid ? "Must be a hex color like #c02434." : hint}
      </p>
    </div>
  );
}

/**
 * Connector-wide branding for MCP Apps views: accent color (light + dark) and
 * a header logo. Saved to the session via elliot_set_branding, so the next
 * build — and every UI-tab preview — picks it up. Text and background always
 * follow the host theme; branding only layers identity on top.
 */
export function BrandingCard() {
  const [accent, setAccent] = useState("");
  const [accentDark, setAccentDark] = useState("");
  const [logo, setLogo] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ type: "ok" | "error"; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await callTool("elliot_get_branding", {});
        const body = res as { branding?: ConnectorBranding | null };
        if (body.branding) {
          setAccent(body.branding.accent ?? "");
          setAccentDark(body.branding.accent_dark ?? "");
          setLogo(body.branding.logo ?? "");
        }
      } catch (err) {
        // Plugin not connected yet is expected on a fresh session.
        console.warn("[BrandingCard] failed to load branding", err);
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const handleLogoFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUri = typeof reader.result === "string" ? reader.result : "";
      if (!dataUri.startsWith("data:image/")) {
        setStatus({ type: "error", message: "That file is not an image." });
        return;
      }
      setLogo(dataUri);
      setStatus(null);
    };
    reader.readAsDataURL(file);
  };

  const logoBytes = logo.startsWith("data:") ? new Blob([logo]).size : 0;
  const logoTooLarge = logoBytes > LOGO_WARN_BYTES;
  const hexInvalid =
    (accent !== "" && !HEX_RE.test(accent)) || (accentDark !== "" && !HEX_RE.test(accentDark));

  const handleSave = async () => {
    setSaving(true);
    setStatus(null);
    try {
      // clear+set = full replace, so removing a color/logo here sticks.
      const res = await callTool("elliot_set_branding", {
        clear: true,
        ...(accent ? { accent } : {}),
        ...(accentDark ? { accent_dark: accentDark } : {}),
        ...(logo ? { logo } : {}),
      });
      const body = res as { status?: string; error?: string | { message?: string } };
      if (body.status === "ok") {
        setStatus({
          type: "ok",
          message:
            accent || logo
              ? "Branding saved — rebuild the connector to ship it; previews use it right away."
              : "Branding cleared.",
        });
      } else {
        const message =
          typeof body.error === "string" ? body.error : (body.error?.message ?? "Save failed");
        setStatus({ type: "error", message });
      }
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card data-testid="branding-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Palette className="h-4 w-4 text-muted-foreground" />
          Branding
        </CardTitle>
        <CardDescription>
          Accent color and logo applied to every tool's interactive view (MCP Apps). Text and
          background stay host-themed so views remain legible in any client.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ColorField
            id="branding-accent"
            label="Accent color"
            hint="Highlights, selection and focus in the views."
            value={accent}
            onChange={setAccent}
          />
          <ColorField
            id="branding-accent-dark"
            label="Dark-theme accent"
            hint="Optional override for dark hosts; empty inherits the accent."
            value={accentDark}
            onChange={setAccentDark}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="branding-logo">Logo</Label>
          <div className="flex items-center gap-3 flex-wrap">
            {logo && (
              <span className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-2 py-1">
                <img src={logo} alt="Connector logo" className="h-6 w-auto max-w-[8rem] object-contain" />
                <button
                  type="button"
                  aria-label="Remove logo"
                  onClick={() => setLogo("")}
                  className="rounded p-0.5 opacity-60 hover:opacity-100 hover:bg-muted"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="h-3.5 w-3.5" />
              Upload image
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              aria-label="Logo file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleLogoFile(file);
                e.target.value = "";
              }}
            />
            <Input
              id="branding-logo"
              value={logo.startsWith("data:") ? "" : logo}
              onChange={(e) => setLogo(e.target.value.trim())}
              placeholder="or paste an https:// image URL"
              className="h-8 flex-1 min-w-48 text-sm"
            />
          </div>
          <p className={logoTooLarge ? "text-2xs text-warning" : "text-2xs text-muted-foreground"}>
            {logoTooLarge
              ? `Logo is ${Math.round(logoBytes / 1024)} KiB — it is inlined into every view; use a small SVG/PNG (≤64 KiB) or an https URL.`
              : "Shown in each view's header. Small SVG or PNG works best; uploads are embedded as data: URIs."}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            type="button"
            size="sm"
            onClick={() => void handleSave()}
            disabled={!loaded || saving || hexInvalid}
          >
            {saving ? "Saving…" : "Save branding"}
          </Button>
          {status && (
            <span
              role={status.type === "error" ? "alert" : "status"}
              className={
                status.type === "ok"
                  ? "flex items-center gap-1.5 text-xs text-success"
                  : "flex items-center gap-1.5 text-xs text-destructive"
              }
            >
              {status.type === "ok" ? (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              )}
              {status.message}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
