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
        if name not in seen:
            seen[name] = 0
            result.append(name)
        else:
            seen[name] += 1
            result.append(f"{name}_{seen[name] + 1}")
    return result
