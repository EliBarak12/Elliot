from __future__ import annotations

from typing import Any

from elliot_core.sql import safe_ident
from elliot_core.types.tool import FilterGroup, ToolDefinition

_OP_MAP: dict[str, str] = {
    "=": "=",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "contains": "LIKE",
    "in_list": "IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
}


def _escape_like(val: Any) -> str:
    """Escape LIKE wildcards so user input is matched literally.

    Without this, an agent passing ``%`` or ``_`` as a ``contains`` value
    would match every row. Backslash must be escaped first (it is the ESCAPE
    character), then ``%`` and ``_``. The generated clause appends
    ``ESCAPE '\\'`` so these escapes are honored.
    """
    s = str(val)
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_select_sql(tool: ToolDefinition, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Convert tool filter_groups / return_fields / having / order_by / limit
    into a safe parameterized SELECT. Returns (sql_string, bound_params_dict).
    """
    bound: dict[str, Any] = {}

    # ── SELECT clause ──────────────────────────────────────────────────────
    has_agg = any(rf.aggregation and rf.aggregation != "none" for rf in tool.return_fields)
    group_by_cols: list[str] = []

    if not tool.return_fields:
        select_clause = "*"
    else:
        parts: list[str] = []
        for rf in tool.return_fields:
            # COUNT(*) special case: field "*" means count all rows. The bare
            # "*" is not a valid identifier, so handle before safe_ident.
            is_star = rf.field == "*"
            col = rf.field.replace(".", "_")
            quoted_col = "*" if is_star else safe_ident(col)
            if rf.aggregation and rf.aggregation != "none":
                alias = rf.alias or f"{rf.aggregation}_{'all' if is_star else col}"
                quoted_alias = safe_ident(alias)
                parts.append(f"{rf.aggregation.upper()}({quoted_col}) AS {quoted_alias}")
            else:
                alias_clause = f" AS {safe_ident(rf.alias)}" if rf.alias and rf.alias != col else ""
                parts.append(f"{quoted_col}{alias_clause}")
                if has_agg and not is_star:
                    group_by_cols.append(quoted_col)  # non-agg fields go into GROUP BY
        select_clause = ", ".join(parts)

    # ── FROM ───────────────────────────────────────────────────────────────
    primary = tool.source_ids[0]
    sql = f"SELECT {select_clause} FROM {safe_ident(primary)}"

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
        order_parts: list[str] = []
        for of in tool.order_by:
            field_col = of.field.replace(".", "_")
            # Direction must be ASC or DESC; reject anything else as injection.
            if of.direction not in ("ASC", "DESC"):
                raise ValueError(f"Invalid ORDER BY direction: {of.direction!r}")
            order_parts.append(f"{safe_ident(field_col)} {of.direction}")
        sql += " ORDER BY " + ", ".join(order_parts)

    # ── LIMIT ──────────────────────────────────────────────────────────────
    # tool.limit is a typed int via Pydantic; safe to f-string.
    sql += f" LIMIT {int(tool.limit)}"

    return sql, bound


def _build_group_parts(
    groups: list[FilterGroup],
    params: dict[str, Any],
    bound: dict[str, Any],
    prefix: str,
) -> list[str]:
    """Convert a list of FilterGroups into WHERE/HAVING clause fragments."""
    # Whitelisted SQL operators — only values present in _OP_MAP can reach the
    # WHERE/HAVING clause. This prevents injection through cond.operator.
    allowed_ops = set(_OP_MAP.values())
    clause_parts: list[str] = []
    for g_idx, group in enumerate(groups):
        group_parts: list[str] = []
        for c_idx, cond in enumerate(group.conditions):
            col = cond.field.replace(".", "_")
            quoted_col = safe_ident(col)
            op = _OP_MAP.get(cond.operator)
            if op is None or op not in allowed_ops:
                # Unknown operator — refuse to build SQL rather than splatter it in.
                continue
            key_base = f"{prefix}_{g_idx}_{c_idx}_{col}"

            if cond.operator in ("is_null", "is_not_null"):
                group_parts.append(f"{quoted_col} {op}")
            elif cond.parameter_name:
                val = params.get(cond.parameter_name)
                if val is None:
                    continue  # optional param not provided — skip condition
                if cond.operator == "contains":
                    bound[key_base] = f"%{_escape_like(val)}%"
                    group_parts.append(f"{quoted_col} LIKE :{key_base} ESCAPE '\\'")
                elif cond.operator == "in_list":
                    vals = val if isinstance(val, list) else str(val).split(",")
                    phs = ", ".join(f":{key_base}_{i}" for i in range(len(vals)))
                    for i, v in enumerate(vals):
                        bound[f"{key_base}_{i}"] = v.strip() if isinstance(v, str) else v
                    group_parts.append(f"{quoted_col} IN ({phs})")
                else:
                    bound[key_base] = val
                    group_parts.append(f"{quoted_col} {op} :{key_base}")
            elif cond.value is not None:
                bound[key_base] = cond.value
                group_parts.append(f"{quoted_col} {op} :{key_base}")

        if group_parts:
            # group.logic comes from a Pydantic typed field — guard anyway.
            logic = group.logic if group.logic in ("AND", "OR") else "AND"
            joined = f" {logic} ".join(group_parts)
            clause_parts.append(f"({joined})")

    return clause_parts
