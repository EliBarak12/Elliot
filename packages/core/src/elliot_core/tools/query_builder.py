from __future__ import annotations

from typing import Any

from elliot_core.types.tool import FilterGroup, ToolDefinition

_OP_MAP: dict[str, str] = {
    "=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<=",
    "contains": "LIKE",
    "in_list": "IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
}


def build_select_sql(tool: ToolDefinition, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Convert tool filter_groups / return_fields / having / order_by / limit
    into a safe parameterized SELECT. Returns (sql_string, bound_params_dict).
    """
    bound: dict[str, Any] = {}

    # ── SELECT clause ──────────────────────────────────────────────────────
    has_agg = any(
        rf.aggregation and rf.aggregation != "none" for rf in tool.return_fields
    )
    group_by_cols: list[str] = []

    if not tool.return_fields:
        select_clause = "*"
    else:
        parts: list[str] = []
        for rf in tool.return_fields:
            col = rf.field.replace(".", "_")
            if rf.aggregation and rf.aggregation != "none":
                alias = rf.alias or f"{rf.aggregation}_{col}"
                # COUNT(*) special case: field "*" means count all rows
                agg_target = "*" if rf.field == "*" else f'"{col}"'
                parts.append(f'{rf.aggregation.upper()}({agg_target}) AS "{alias}"')
            else:
                alias_clause = f' AS "{rf.alias}"' if rf.alias and rf.alias != col else ""
                parts.append(f'"{col}"{alias_clause}')
                if has_agg:
                    group_by_cols.append(f'"{col}"')  # non-agg fields go into GROUP BY
        select_clause = ", ".join(parts)

    # ── FROM ───────────────────────────────────────────────────────────────
    primary = tool.source_ids[0]
    sql = f'SELECT {select_clause} FROM "{primary}"'

    # ── WHERE ──────────────────────────────────────────────────────────────
    where_parts = _build_group_parts(tool.filter_groups, params, bound, prefix="w")
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    # ── GROUP BY (auto-derived from non-aggregated return fields) ──────────
    if group_by_cols:
        sql += " GROUP BY " + ", ".join(group_by_cols)

    # ── HAVING ─────────────────────────────────────────────────────────────
    if tool.having:
        having_parts = _build_group_parts(tool.having, params, bound, prefix="h")
        if having_parts:
            sql += " HAVING " + " AND ".join(having_parts)

    # ── ORDER BY ───────────────────────────────────────────────────────────
    if tool.order_by:
        order_parts = [
            f'"{of.field.replace(".", "_")}" {of.direction}'
            for of in tool.order_by
        ]
        sql += " ORDER BY " + ", ".join(order_parts)

    # ── LIMIT ──────────────────────────────────────────────────────────────
    sql += f" LIMIT {tool.limit}"

    return sql, bound


def _build_group_parts(
    groups: list[FilterGroup],
    params: dict[str, Any],
    bound: dict[str, Any],
    prefix: str,
) -> list[str]:
    """Convert a list of FilterGroups into WHERE/HAVING clause fragments."""
    clause_parts: list[str] = []
    for g_idx, group in enumerate(groups):
        group_parts: list[str] = []
        for c_idx, cond in enumerate(group.conditions):
            col = cond.field.replace(".", "_")
            op = _OP_MAP.get(cond.operator, cond.operator)
            key_base = f"{prefix}_{g_idx}_{c_idx}_{col}"

            if cond.operator in ("is_null", "is_not_null"):
                group_parts.append(f'"{col}" {op}')
            elif cond.parameter_name:
                val = params.get(cond.parameter_name)
                if val is None:
                    continue  # optional param not provided — skip condition
                if cond.operator == "contains":
                    bound[key_base] = f"%{val}%"
                    group_parts.append(f'"{col}" LIKE :{key_base}')
                elif cond.operator == "in_list":
                    vals = val if isinstance(val, list) else str(val).split(",")
                    phs = ", ".join(f":{key_base}_{i}" for i in range(len(vals)))
                    for i, v in enumerate(vals):
                        bound[f"{key_base}_{i}"] = v.strip() if isinstance(v, str) else v
                    group_parts.append(f'"{col}" IN ({phs})')
                else:
                    bound[key_base] = val
                    group_parts.append(f'"{col}" {op} :{key_base}')
            elif cond.value is not None:
                bound[key_base] = cond.value
                group_parts.append(f'"{col}" {op} :{key_base}')

        if group_parts:
            joined = f" {group.logic} ".join(group_parts)
            clause_parts.append(f"({joined})")

    return clause_parts
