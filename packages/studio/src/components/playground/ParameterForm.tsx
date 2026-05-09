import { Input } from "@/components/ui/input";
import type { ParameterDefinition } from "@/types/api";

interface Props {
  parameters: ParameterDefinition[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
}

export function ParameterForm({ parameters, values, onChange }: Props) {
  const set = (name: string, val: string) => onChange({ ...values, [name]: val });

  if (parameters.length === 0) {
    return <p className="text-xs text-muted-foreground">No parameters</p>;
  }

  return (
    <div className="space-y-3">
      {parameters.map((p) => (
        <div key={p.name}>
          <label className="text-xs font-medium">
            {p.name}
            {p.required && <span className="text-destructive ml-0.5">*</span>}
            <span className="text-muted-foreground ml-1 font-normal">({p.type})</span>
          </label>

          {p.type === "boolean" ? (
            <div className="flex items-center gap-2 mt-1">
              <input
                type="checkbox"
                id={p.name}
                checked={values[p.name] === "true"}
                onChange={(e) => set(p.name, e.target.checked ? "true" : "false")}
              />
              <label htmlFor={p.name} className="text-sm">
                {values[p.name] === "true" ? "true" : "false"}
              </label>
            </div>
          ) : (
            <Input
              type={p.type === "integer" || p.type === "number" ? "number" : p.type === "date" ? "date" : "text"}
              value={values[p.name] ?? ""}
              onChange={(e) => set(p.name, e.target.value)}
              placeholder={p.description || p.type}
              className="mt-1 h-8 text-sm"
            />
          )}
        </div>
      ))}
    </div>
  );
}
