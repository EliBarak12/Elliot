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


# SQLite identifiers are bounded to 63 chars by elliot_core.sql.safe_ident so a
# connector can't DoS the engine with a giant name; keep safe_name within that.
_MAX_NAME_LEN = 63


def safe_name(raw: str) -> str:
    """Convert an arbitrary string to a safe SQLite column name.

    Unicode letters and digits are preserved (``\\w`` is Unicode-aware), so a
    Hebrew header like ``שם רופא`` becomes ``שם_רופא`` rather than collapsing to
    ``col`` and destroying the column's data (P1). Only characters that are
    unsafe or meaningless in an identifier — whitespace, punctuation, quotes —
    are replaced with ``_``. The result always satisfies
    :func:`elliot_core.sql.safe_ident`'s identifier rule.
    """
    name = raw.lower()
    # Replace every non-word character (anything that isn't a Unicode letter,
    # digit, or underscore) with ``_``. This keeps Hebrew/CJK/accented letters.
    name = re.sub(r"\W", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("_")
    # Bound length BEFORE the digit/empty fixups so the final value still fits
    # safe_ident's 63-char limit even after a ``col_`` prefix.
    if len(name) > _MAX_NAME_LEN:
        name = name[:_MAX_NAME_LEN].strip("_")
    if name and name[0].isdigit():
        name = ("col_" + name)[:_MAX_NAME_LEN]
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
