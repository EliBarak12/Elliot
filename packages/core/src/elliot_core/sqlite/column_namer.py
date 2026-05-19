from __future__ import annotations

import re

SQL_RESERVED = frozenset(
    {
        "select",
        "from",
        "where",
        "group",
        "order",
        "limit",
        "index",
        "table",
        "create",
        "drop",
        "insert",
        "update",
        "delete",
        "join",
        "on",
        "as",
        "by",
        "and",
        "or",
        "not",
        "null",
        "is",
        "in",
        "values",
    }
)


def safe_name(raw: str) -> str:
    """Convert an arbitrary string to a safe SQLite column name."""
    name = raw.lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = "col_" + name
    if not name:
        name = "col"
    if name in SQL_RESERVED:
        name = name + "_col"
    return name


def deduplicate_names(names: list[str]) -> list[str]:
    """Append _2, _3, etc. to resolve duplicate column names."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        result.append(disambiguate(name, seen))
    return result


def disambiguate(name: str, seen: dict[str, int]) -> str:
    """Return ``name`` (first use) or ``name_2``, ``name_3``, ... on collision.

    ``seen`` is mutated in place — the caller owns the disambiguation
    table, so the same instance can be threaded through the row-level
    flattener and the column-meta builder. This guarantees that a key
    collision is resolved to the same suffix in both layers, preventing
    silent data loss where a row would carry the value under one name
    while the schema declared it under another.
    """
    if name not in seen:
        seen[name] = 0
        return name
    seen[name] += 1
    return f"{name}_{seen[name] + 1}"
