import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { callTool } from "@/lib/mcp-client";
import { useSources } from "@/hooks/useSources";
import { FilterGroupBuilder, type FilterGroup } from "./FilterGroupBuilder";
import { ReturnFieldSelector, type ReturnField } from "./ReturnFieldSelector";
import { ApiMappingForm, type ApiRequestMapping } from "./ApiMappingForm";
import { ToolTester } from "./ToolTester";
import type { ToolDefinition, ParameterDefinition } from "@/types/api";

type Category = "READ" | "WRITE" | "ACTION" | "AGGREGATE";

interface Props {
  tool: ToolDefinition | null;
  onSaved: () => void;
}

const ID_RE = /^[a-z][a-z0-9_]*$/;

const DEFAULT_API_MAPPING: ApiRequestMapping = {
  method: "POST",
  path_template: "",
  query_params: [],
  body_params: [],
  body_format: "json",
};

export function ToolEditor({ tool, onSaved }: Props) {
  const { data: sourcesRaw } = useSources();
  const sources = Array.isArray(sourcesRaw)
    ? (sourcesRaw as Array<{ id: string; name: string }>)
    : [];

  const [id, setId] = useState(tool?.id ?? "");
  const [name, setName] = useState(tool?.name ?? "");
  const [description, setDescription] = useState(tool?.description ?? "");
  const [category, setCategory] = useState<Category>((tool?.category as Category) ?? "READ");
  const [sourceIds, setSourceIds] = useState<string[]>(tool?.source_ids ?? []);
  const [parameters, setParameters] = useState<ParameterDefinition[]>(tool?.parameters ?? []);
  const [filterGroups, setFilterGroups] = useState<FilterGroup[]>([]);
  const [returnFields, setReturnFields] = useState<ReturnField[]>([]);
  const [apiMapping, setApiMapping] = useState<ApiRequestMapping>(DEFAULT_API_MAPPING);
  const [saved, setSaved] = useState(false);
  const [status, setStatus] = useState<{ type: "ok" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (!tool) return;
    setId(tool.id);
    setName(tool.name);
    setDescription(tool.description);
    setCategory((tool.category as Category) ?? "READ");
    setSourceIds(tool.source_ids ?? []);
    setParameters(tool.parameters ?? []);
    setSaved(false);
    setStatus(null);
  }, [tool]);

  const idValid = ID_RE.test(id);
  const isRead = category === "READ" || category === "AGGREGATE";

  const buildPayload = () => ({
    id,
    name,
    description,
    category,
    source_ids: sourceIds,
    parameters,
    ...(isRead ? { filter_groups: filterGroups, return_fields: returnFields } : { api_mapping: apiMapping }),
  });

  const handleValidate = async () => {
    setStatus(null);
    try {
      const res = await callTool("elliot_validate_tool", { tool: buildPayload() });
      const r = res as { valid?: boolean; error?: string };
      setStatus(r.valid ? { type: "ok", message: "Validation passed ✓" } : { type: "error", message: r.error ?? "Invalid" });
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const handleSave = async () => {
    setStatus(null);
    try {
      const toolName = tool ? "elliot_update_tool" : "elliot_create_tool";
      await callTool(toolName, { tool: buildPayload() });
      setSaved(true);
      setStatus({ type: "ok", message: "Saved ✓" });
      onSaved();
    } catch (err) {
      setStatus({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const toggleSource = (sid: string) =>
    setSourceIds((prev) =>
      prev.includes(sid) ? prev.filter((s) => s !== sid) : [...prev, sid]
    );

  const addParam = () =>
    setParameters((prev) => [
      ...prev,
      { name: "", type: "string", required: true, description: "", default: null },
    ]);

  const updateParam = (i: number, p: ParameterDefinition) => {
    const next = [...parameters];
    next[i] = p;
    setParameters(next);
  };

  return (
    <div className="space-y-4 p-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium text-muted-foreground">ID</label>
          <Input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="my_tool_id"
            className={`mt-1 h-8 text-sm ${!idValid && id ? "border-destructive" : ""}`}
          />
          {!idValid && id && (
            <p className="text-xs text-destructive mt-0.5">Must match [a-z][a-z0-9_]*</p>
          )}
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">Name</label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Tool"
            className="mt-1 h-8 text-sm"
          />
        </div>
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground">
          Description{" "}
          <span className={`text-xs ${description.length >= 20 ? "text-green-600" : "text-muted-foreground"}`}>
            ({description.length} chars, target ≥ 20)
          </span>
        </label>
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What does this tool do?"
          className="mt-1 text-sm min-h-[60px]"
        />
      </div>

      <div className="flex gap-2 items-center flex-wrap">
        <span className="text-xs font-medium text-muted-foreground">Category:</span>
        {(["READ", "WRITE", "ACTION", "AGGREGATE"] as Category[]).map((c) => (
          <button key={c} type="button" onClick={() => setCategory(c)}>
            <Badge variant={category === c ? "default" : "outline"} className="cursor-pointer">
              {c}
            </Badge>
          </button>
        ))}
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground">Sources</label>
        <div className="flex flex-wrap gap-2 mt-1">
          {sources.map((s) => (
            <button key={s.id} type="button" onClick={() => toggleSource(s.id)}>
              <Badge
                variant={sourceIds.includes(s.id) ? "default" : "outline"}
                className="cursor-pointer"
              >
                {s.name}
              </Badge>
            </button>
          ))}
          {sources.length === 0 && (
            <span className="text-xs text-muted-foreground">No sources available</span>
          )}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-medium text-muted-foreground">Parameters</label>
          <Button type="button" size="sm" variant="outline" className="h-6 text-xs" onClick={addParam}>
            + Add
          </Button>
        </div>
        {parameters.map((p, i) => (
          <div key={i} className="flex gap-2 mb-2 items-center flex-wrap">
            <Input
              placeholder="name"
              value={p.name}
              onChange={(e) => updateParam(i, { ...p, name: e.target.value })}
              className="h-7 text-xs w-28"
            />
            <select
              value={p.type}
              onChange={(e) => updateParam(i, { ...p, type: e.target.value as ParameterDefinition["type"] })}
              className="h-7 text-xs border rounded px-1"
            >
              {["string", "integer", "number", "boolean", "date"].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={p.required}
                onChange={(e) => updateParam(i, { ...p, required: e.target.checked })}
              />
              required
            </label>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 text-xs px-1"
              onClick={() => setParameters((prev) => prev.filter((_, idx) => idx !== i))}
            >
              ×
            </Button>
          </div>
        ))}
      </div>

      {isRead ? (
        <>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-2">
              Filter conditions
            </label>
            <FilterGroupBuilder
              groups={filterGroups}
              onChange={setFilterGroups}
              availableFields={[]}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-2">
              Return fields
            </label>
            <ReturnFieldSelector fields={returnFields} onChange={setReturnFields} />
          </div>
        </>
      ) : (
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-2">
            API mapping
          </label>
          <ApiMappingForm value={apiMapping} onChange={setApiMapping} />
        </div>
      )}

      {status && (
        <div
          className={`text-xs px-3 py-2 rounded border ${
            status.type === "ok"
              ? "bg-green-50 border-green-200 text-green-800"
              : "bg-destructive/10 border-destructive/20 text-destructive"
          }`}
        >
          {status.message}
        </div>
      )}

      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => void handleValidate()}>
          Validate
        </Button>
        <Button size="sm" disabled={!idValid} onClick={() => void handleSave()}>
          Save
        </Button>
      </div>

      {saved && (
        <div className="border rounded-md p-3">
          <p className="text-xs font-medium text-muted-foreground mb-2">Test</p>
          <ToolTester toolId={id} parameters={parameters} />
        </div>
      )}
    </div>
  );
}
