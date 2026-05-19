import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface FilterCondition {
  field: string;
  operator: string;
  value: string | null;
  parameter_name: string | null;
}

export interface FilterGroup {
  logic: "AND" | "OR";
  conditions: FilterCondition[];
}

const OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "contains", "in_list", "is_null", "is_not_null"];

interface Props {
  groups: FilterGroup[];
  onChange: (groups: FilterGroup[]) => void;
  availableFields: string[];
}

export function FilterGroupBuilder({ groups, onChange, availableFields }: Props) {
  // One datalist for the whole builder — rendering it per condition row
  // produced duplicate DOM ids, so only the first ever bound.
  const fieldsListId = useId();

  const updateGroup = (i: number, g: FilterGroup) => {
    const next = [...groups];
    next[i] = g;
    onChange(next);
  };

  const addGroup = () =>
    onChange([...groups, { logic: "AND", conditions: [] }]);

  const removeGroup = (i: number) =>
    onChange(groups.filter((_, idx) => idx !== i));

  return (
    <div className="space-y-3">
      <datalist id={fieldsListId}>
        {availableFields.map((f) => (
          <option key={f} value={f} />
        ))}
      </datalist>
      {groups.map((group, gi) => (
        <div key={gi} className="border rounded-md p-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium">Logic:</span>
            <button
              type="button"
              onClick={() => updateGroup(gi, { ...group, logic: group.logic === "AND" ? "OR" : "AND" })}
              className="text-xs border rounded px-2 py-0.5 hover:bg-accent"
            >
              {group.logic}
            </button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="ml-auto h-6 text-xs"
              onClick={() => removeGroup(gi)}
            >
              Remove group
            </Button>
          </div>

          {group.conditions.map((cond, ci) => (
            <div key={ci} className="flex items-center gap-2 flex-wrap">
              <Input
                list={fieldsListId}
                placeholder="field"
                value={cond.field}
                onChange={(e) => {
                  const next = [...group.conditions];
                  next[ci] = { ...cond, field: e.target.value };
                  updateGroup(gi, { ...group, conditions: next });
                }}
                className="w-32 h-7 text-xs"
              />

              <select
                value={cond.operator}
                onChange={(e) => {
                  const next = [...group.conditions];
                  next[ci] = { ...cond, operator: e.target.value };
                  updateGroup(gi, { ...group, conditions: next });
                }}
                className="h-7 text-xs border rounded px-1"
              >
                {OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
              </select>

              {!["is_null", "is_not_null"].includes(cond.operator) && (
                <>
                  <select
                    value={cond.parameter_name ? "param" : "fixed"}
                    onChange={(e) => {
                      const next = [...group.conditions];
                      next[ci] = e.target.value === "param"
                        ? { ...cond, parameter_name: "", value: null }
                        : { ...cond, parameter_name: null, value: "" };
                      updateGroup(gi, { ...group, conditions: next });
                    }}
                    className="h-7 text-xs border rounded px-1"
                  >
                    <option value="fixed">Fixed</option>
                    <option value="param">Parameter</option>
                  </select>

                  {cond.parameter_name !== null ? (
                    <Input
                      placeholder="param_name"
                      value={cond.parameter_name}
                      onChange={(e) => {
                        const next = [...group.conditions];
                        next[ci] = { ...cond, parameter_name: e.target.value };
                        updateGroup(gi, { ...group, conditions: next });
                      }}
                      className="w-28 h-7 text-xs"
                    />
                  ) : (
                    <Input
                      placeholder="value"
                      value={cond.value ?? ""}
                      onChange={(e) => {
                        const next = [...group.conditions];
                        next[ci] = { ...cond, value: e.target.value };
                        updateGroup(gi, { ...group, conditions: next });
                      }}
                      className="w-28 h-7 text-xs"
                    />
                  )}
                </>
              )}

              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-6 text-xs px-1"
                onClick={() => {
                  const next = group.conditions.filter((_, idx) => idx !== ci);
                  updateGroup(gi, { ...group, conditions: next });
                }}
              >
                ×
              </Button>
            </div>
          ))}

          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-6 text-xs"
            onClick={() => {
              const next = [...group.conditions, { field: "", operator: "=", value: "", parameter_name: null }];
              updateGroup(gi, { ...group, conditions: next });
            }}
          >
            + Add condition
          </Button>
        </div>
      ))}

      <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={addGroup}>
        + Add group
      </Button>
    </div>
  );
}
