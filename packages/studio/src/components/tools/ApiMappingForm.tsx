import { Input } from "@/components/ui/input";

export interface ApiRequestMapping {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path_template: string;
  query_params: string[];
  body_params: string[];
  body_format: "json" | "form";
}

interface Props {
  value: ApiRequestMapping;
  onChange: (m: ApiRequestMapping) => void;
}

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
type Method = (typeof HTTP_METHODS)[number];

function TagInput({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      <div className="flex flex-wrap gap-1 mt-1">
        {values.map((v, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 bg-secondary text-secondary-foreground text-xs rounded px-2 py-0.5"
          >
            {v}
            <button
              type="button"
              onClick={() => onChange(values.filter((_, idx) => idx !== i))}
              className="hover:text-destructive"
            >
              ×
            </button>
          </span>
        ))}
        <input
          className="text-xs border-b outline-none bg-transparent w-20"
          placeholder="add…"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              const val = (e.target as HTMLInputElement).value.trim();
              if (val) {
                onChange([...values, val]);
                (e.target as HTMLInputElement).value = "";
              }
            }
          }}
        />
      </div>
    </div>
  );
}

export function ApiMappingForm({ value, onChange }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <div>
          <label className="text-xs font-medium text-muted-foreground">Method</label>
          <select
            value={value.method}
            onChange={(e) => onChange({ ...value, method: e.target.value as Method })}
            className="block h-8 text-sm border rounded px-2 mt-1"
          >
            {HTTP_METHODS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="text-xs font-medium text-muted-foreground">
            Path template <span className="text-xs font-normal opacity-60">(use {"{"} param {"}"} )</span>
          </label>
          <Input
            placeholder="/users/{user_id}"
            value={value.path_template}
            onChange={(e) => onChange({ ...value, path_template: e.target.value })}
            className="h-8 text-sm mt-1"
          />
        </div>
      </div>

      <TagInput
        label="Query params"
        values={value.query_params}
        onChange={(v) => onChange({ ...value, query_params: v })}
      />
      <TagInput
        label="Body params"
        values={value.body_params}
        onChange={(v) => onChange({ ...value, body_params: v })}
      />

      <div>
        <label className="text-xs font-medium text-muted-foreground">Body format</label>
        <select
          value={value.body_format}
          onChange={(e) =>
            onChange({ ...value, body_format: e.target.value as "json" | "form" })
          }
          className="block h-8 text-sm border rounded px-2 mt-1"
        >
          <option value="json">JSON</option>
          <option value="form">Form</option>
        </select>
      </div>
    </div>
  );
}
