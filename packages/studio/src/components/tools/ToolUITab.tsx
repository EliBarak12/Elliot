import { useMemo, useState } from "react";
import { Eye } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { callTool } from "@/lib/mcp-client";
import { AppResultView } from "@/components/playground/AppPreviewHost";
import type { ReturnField } from "./ReturnFieldSelector";
import type { ToolUiConfig } from "@/types/api";

const PRESETS: Array<{ id: ToolUiConfig["preset"]; label: string; pending?: boolean }> = [
  { id: "auto", label: "Auto" },
  { id: "table", label: "Table" },
  { id: "detail", label: "Detail" },
  { id: "metric", label: "Metrics" },
  { id: "markdown", label: "Markdown" },
  { id: "chart", label: "Chart", pending: true },
  { id: "form", label: "Form", pending: true },
];

export const DEFAULT_UI_CONFIG: ToolUiConfig = {
  enabled: true,
  preset: "auto",
  title: null,
  mapping: {},
  custom_html: null,
  csp_connect_domains: [],
  prefer_border: true,
  visibility: ["model", "app"],
};

/** Which mapping slot each preset reads (comma-separated field names). */
function mappingSlot(preset: ToolUiConfig["preset"]): { key: string; label: string } | null {
  switch (preset) {
    case "table":
      return { key: "columns", label: "Columns" };
    case "detail":
      return { key: "fields", label: "Fields" };
    case "metric":
      return { key: "value_fields", label: "Value fields" };
    default:
      return null;
  }
}

interface Props {
  toolId: string;
  value: ToolUiConfig | null;
  onChange: (next: ToolUiConfig | null) => void;
  returnFields: ReturnField[];
}

/**
 * Authoring surface for a tool's MCP Apps view: pick a shadcn preset, wire
 * result fields into it, declare CSP origins — then preview the exact
 * document agents' hosts will render, against live preview data.
 */
export function ToolUITab({ toolId, value, onChange, returnFields }: Props) {
  const [previewing, setPreviewing] = useState(false);
  const [previewData, setPreviewData] = useState<unknown>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const ui = value ?? DEFAULT_UI_CONFIG;
  const enabled = value !== null && ui.enabled;
  const slot = mappingSlot(ui.preset);
  const fieldHints = useMemo(
    () => returnFields.map((f) => f.alias || f.field).filter(Boolean),
    [returnFields]
  );

  const update = (patch: Partial<ToolUiConfig>) => onChange({ ...ui, ...patch });

  const handlePreview = async () => {
    setPreviewError(null);
    setPreviewing(true);
    try {
      const res = (await callTool("elliot_preview_tool", {
        tool_id: toolId,
        params: {},
      })) as unknown;
      setPreviewData(res);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
      setPreviewData(null);
    }
  };

  return (
    <div className="border rounded-md p-3 space-y-3" data-testid="tool-ui-tab">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-muted-foreground">Interactive view (MCP Apps)</p>
          <p className="text-2xs text-muted-foreground">
            Hosts like Claude render this for the tool's results in a sandboxed iframe. Agents
            without Apps support keep getting the plain result — declaring a view costs nothing.
          </p>
        </div>
        <label className="flex items-center gap-1.5 text-xs shrink-0">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onChange(e.target.checked ? { ...ui, enabled: true } : null)}
          />
          enabled
        </label>
      </div>

      {enabled && (
        <>
          <div className="flex gap-2 items-center flex-wrap">
            <span className="text-xs font-medium text-muted-foreground">Preset:</span>
            {PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={p.pending}
                title={p.pending ? "Coming soon — renders as Auto for now" : undefined}
                onClick={() => update({ preset: p.id })}
              >
                <Badge
                  variant={ui.preset === p.id ? "default" : "outline"}
                  className={p.pending ? "opacity-50" : "cursor-pointer"}
                >
                  {p.label}
                </Badge>
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground">View title</label>
              <Input
                value={ui.title ?? ""}
                onChange={(e) => update({ title: e.target.value || null })}
                placeholder="Defaults to the tool name"
                className="mt-1 h-8 text-sm"
              />
            </div>
            {slot && (
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  {slot.label}{" "}
                  <span className="font-normal opacity-60">(comma-separated field names)</span>
                </label>
                <Input
                  value={ui.mapping[slot.key] ?? ""}
                  onChange={(e) =>
                    update({ mapping: { ...ui.mapping, [slot.key]: e.target.value } })
                  }
                  placeholder={fieldHints.length ? fieldHints.join(",") : "id,name,status"}
                  className="mt-1 h-8 text-sm font-mono"
                />
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Allowed external origins{" "}
                <span className="font-normal opacity-60">(CSP connect domains)</span>
              </label>
              <Input
                value={ui.csp_connect_domains.join(",")}
                onChange={(e) =>
                  update({
                    csp_connect_domains: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="https://api.example.com"
                className="mt-1 h-8 text-sm font-mono"
              />
            </div>
            <div className="flex items-end gap-4 pb-1">
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={ui.prefer_border}
                  onChange={(e) => update({ prefer_border: e.target.checked })}
                />
                border
              </label>
              <label className="flex items-center gap-1.5 text-xs" title="Who may call this tool">
                visibility
                <select
                  value={ui.visibility.length === 2 ? "both" : ui.visibility[0]}
                  onChange={(e) =>
                    update({
                      visibility:
                        e.target.value === "both"
                          ? ["model", "app"]
                          : [e.target.value as "model" | "app"],
                    })
                  }
                  className="h-7 text-xs border rounded px-1"
                >
                  <option value="both">model + app</option>
                  <option value="model">model only</option>
                  <option value="app">app only</option>
                </select>
              </label>
            </div>
          </div>

          <div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() => void handlePreview()}
            >
              <Eye className="h-3.5 w-3.5" />
              Preview view
            </Button>
            <span className="ml-2 text-2xs text-muted-foreground">
              Runs the tool with empty params and renders the result in the view.
            </span>
          </div>
          {previewError && <p className="text-xs text-destructive">{previewError}</p>}
          {previewing && previewData !== null && (
            <AppResultView
              toolId={toolId}
              args={{}}
              resultData={previewData}
              draftUi={ui as unknown as Record<string, unknown>}
            />
          )}
        </>
      )}
    </div>
  );
}
