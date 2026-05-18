from __future__ import annotations

from collections.abc import Callable
from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.sql import is_valid_ident, safe_ident
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


def _quote_mysql(name: str) -> str:
    """Validate ``name`` and wrap it in MySQL backticks.

    MySQL only accepts double quotes as identifier quotes under the
    non-default ``ANSI_QUOTES`` sql_mode, so the ANSI quoter is unsafe
    there. Validation is identical to :func:`safe_ident`.
    """
    if not is_valid_ident(name):
        raise ElliotError(
            "INVALID_IDENTIFIER",
            "identifier must match ^[A-Za-z_][A-Za-z0-9_]{0,62}$",
            detail={"value": str(name)[:64]},
        )
    return f"`{name}`"


# SQLite and Postgres share the ANSI double-quote identifier quote; MySQL
# uses backticks. Keyed by dialect so a tool's filter_groups compile to a
# SELECT that runs either against the in-memory SQLite mirror or, when the
# runtime pushes the filter down, straight against the real DB source.
_QUOTERS: dict[str, Callable[[str], str]] = {
    "sqlite": safe_ident,
    "postgres": safe_ident,
    "mysql": _quote_mysql,
}


def quote_ident(name: str, dialect: str = "sqlite") -> str:
    """Validate ``name`` as a SQL identifier and quote it for ``dialect``."""
    return _QUOTERS.get(dialect, safe_ident)(name)


def _escape_like(val: Any) -> str:
    """Escape LIKE wildcards so user input is matched literally.

    Without this, an agent passing ``%`` or ``_`` as a ``contains`` value
    would match every row. Backslash must be escaped first (it is the ESCAPE
    character), then ``%`` and ``_``. The generated clause appends
    ``ESCAPE '\\'`` so these escapes are honored.
    """
    s = str(val)
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_select_sql(
    tool: ToolDefinition,
    params: dict[str, Any],
    *,
    dialect: str = "sqlite",
    from_clause: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Convert tool filter_groups / return_fields / having / order_by / limit
    into a safe parameterized SELECT. Returns (sql_string, bound_params_dict).

    ``dialect`` selects identifier quoting — ``sqlite``/``postgres`` use ANSI
    double quotes, ``mysql`` uses backticks — so the same compiled query can
    run against the in-memory SQLite mirror or be pushed straight to a
    Postgres/MySQL source. ``from_clause`` overrides the FROM expression
    (used by the runtime's DB push-down to target the real table or to wrap
    a custom source query); when omitted the first source id is used.
    """
    quote = _QUOTERS.get(dialect, safe_ident)
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
            # "*" is not a valid identifier, so handle before the quoter.
            is_star = rf.field == "*"
            col = rf.field.replace(".", "_")
            quoted_col = "*" if is_star else quote(col)
            if rf.aggregation and rf.aggregation != "none":
                alias = rf.alias or f"{rf.aggregation}_{'all' if is_star else col}"
                quoted_alias = quote(alias)
                parts.append(f"{rf.aggregation.upper()}({quoted_col}) AS {quoted_alias}")
            else:
                alias_clause = f" AS {quote(rf.alias)}" if rf.alias and rf.alias != col else ""
                parts.append(f"{quoted_col}{alias_clause}")
                if has_agg and not is_star:
                    group_by_cols.append(quoted_col)  # non-agg fields go into GROUP BY
        select_clause = ", ".join(parts)

    # ── FROM ───────────────────────────────────────────────────────────────
    from_expr = from_clause if from_clause is not None else quote(tool.source_ids[0])
    sql = f"SELECT {select_clause} FROM {from_expr}"

    # ── WHERE ──────────────────────────────────────────────────────────────
    where_parts = _build_group_parts(
        tool.filter_groups, params, bound, prefix="w", quote=quote, dialect=dialect
    )
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    # ── GROUP BY (auto-derived from non-aggregated return fields) ──────────
    if group_by_cols:
        sql += " GROUP BY " + ", ".join(group_by_cols)

    # ── HAVING ─────────────────────────────────────────────────────────────
    if tool.having:
        having_parts = _build_group_parts(
            tool.having, params, bound, prefix="h", quote=quote, dialect=dialect
        )
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
            order_parts.append(f"{quote(field_col)} {of.direction}")
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
    quote: Callable[[str], str] = safe_ident,
    dialect: str = "sqlite",
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
            quoted_col = quote(col)
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
                    # MySQL string literals treat backslash as an escape, so
                    # the ESCAPE clause needs a doubled backslash there;
                    # SQLite and Postgres take a lone backslash literally.
                    esc = "\\\\" if dialect == "mysql" else "\\"
                    group_parts.append(f"{quoted_col} LIKE :{key_base} ESCAPE '{esc}'")
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
