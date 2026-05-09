import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface ReturnField {
  field: string;
  alias?: string;
  aggregation?: string;
}

const AGGREGATIONS = ["", "COUNT", "SUM", "AVG", "MIN", "MAX"];

interface Props {
  fields: ReturnField[];
  onChange: (fields: ReturnField[]) => void;
}

export function ReturnFieldSelector({ fields, onChange }: Props) {
  const update = (i: number, f: ReturnField) => {
    const next = [...fields];
    next[i] = f;
    onChange(next);
  };

  const remove = (i: number) => onChange(fields.filter((_, idx) => idx !== i));

  const moveUp = (i: number) => {
    if (i === 0) return;
    const next = [...fields];
    [next[i - 1], next[i]] = [next[i], next[i - 1]];
    onChange(next);
  };

  const moveDown = (i: number) => {
    if (i === fields.length - 1) return;
    const next = [...fields];
    [next[i], next[i + 1]] = [next[i + 1], next[i]];
    onChange(next);
  };

  return (
    <div className="space-y-2">
      {fields.map((f, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="flex flex-col">
            <Button type="button" size="sm" variant="ghost" className="h-4 text-xs p-0" onClick={() => moveUp(i)}>▲</Button>
            <Button type="button" size="sm" variant="ghost" className="h-4 text-xs p-0" onClick={() => moveDown(i)}>▼</Button>
          </div>
          <Input
            placeholder="field"
            value={f.field}
            onChange={(e) => update(i, { ...f, field: e.target.value })}
            className="h-7 text-xs w-32"
          />
          <Input
            placeholder="alias"
            value={f.alias ?? ""}
            onChange={(e) => update(i, { ...f, alias: e.target.value || undefined })}
            className="h-7 text-xs w-24"
          />
          <select
            value={f.aggregation ?? ""}
            onChange={(e) => update(i, { ...f, aggregation: e.target.value || undefined })}
            className="h-7 text-xs border rounded px-1"
          >
            {AGGREGATIONS.map((a) => <option key={a} value={a}>{a || "none"}</option>)}
          </select>
          <Button type="button" size="sm" variant="ghost" className="h-6 text-xs px-1" onClick={() => remove(i)}>
            ×
          </Button>
        </div>
      ))}
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-7 text-xs"
        onClick={() => onChange([...fields, { field: "" }])}
      >
        + Add return field
      </Button>
    </div>
  );
}
