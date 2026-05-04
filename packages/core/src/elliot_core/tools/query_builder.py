from __future__ import annotations

from typing import Any

from elliot_core.types.tool import ToolDefinition

_OP_MAP: dict[str, str] = {
    "=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<=",
    "contains": "LIKE",
    "in_list": "IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
}


def build_select_sql(tool: ToolDefinition, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Convert tool.filter_groups + return_fields + limit into a safe
    parameterized SELECT. Returns (sql_string, bound_params_dict).
    """
    # SELECT clause
    if not tool.return_fields:
        select_clause = "*"
    else:
        parts: list[str] = []
        for rf in tool.return_fields:
            col = rf.field.replace(".", "_")
            if rf.aggregation and rf.aggregation != "none":
                alias = rf.alias or col
                parts.append(f'{rf.aggregation.upper()}("{col}") AS "{alias}"')
            else:
                alias_clause = f' AS "{rf.alias}"' if rf.alias and rf.alias != col else ""
                parts.append(f'"{col}"{alias_clause}')
        select_clause = ", ".join(parts)

    primary = tool.source_ids[0]
    sql = f'SELECT {select_clause} FROM "{primary}"'

    bound: dict[str, Any] = {}
    where_parts: list[str] = []

    for group in tool.filter_groups:
        group_parts: list[str] = []
        for cond in group.conditions:
            col = cond.field.replace(".", "_")
            op = _OP_MAP.get(cond.operator, cond.operator)

            if cond.operator in ("is_null", "is_not_null"):
                group_parts.append(f'"{col}" {op}')
            elif cond.parameter_name:
                val = params.get(cond.parameter_name)
                if val is None:
                    continue  # optional param not provided — skip
                key = f"p_{cond.parameter_name}"
                if cond.operator == "contains":
                    bound[key] = f"%{val}%"
                    group_parts.append(f'"{col}" LIKE :{key}')
                elif cond.operator == "in_list":
                    vals = val if isinstance(val, list) else str(val).split(",")
                    placeholders = ", ".join(f":{key}_{i}" for i in range(len(vals)))
                    for i, v in enumerate(vals):
                        bound[f"{key}_{i}"] = v.strip() if isinstance(v, str) else v
                    group_parts.append(f'"{col}" IN ({placeholders})')
                else:
                    bound[key] = val
                    group_parts.append(f'"{col}" {op} :{key}')
            elif cond.value is not None:
                key = f"fixed_{col}"
                bound[key] = cond.value
                group_parts.append(f'"{col}" {op} :{key}')

        if group_parts:
            joined = f" {group.logic} ".join(group_parts)
            where_parts.append(f"({joined})")

    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    sql += f" LIMIT {tool.limit}"
    return sql, bound
