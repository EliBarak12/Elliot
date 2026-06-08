from __future__ import annotations

import hashlib
import re

# SQLite-safe identifier length: ``safe_ident`` accepts
# ``^[A-Za-z_][A-Za-z0-9_]{0,62}$`` — one leading char plus up to 62 more = 63.
# Deeply nested objects inline into long composite column names (e.g.
# ``sprites_versions_generation_viii_brilliant_diamond_shining_pearl_front_default``)
# that blow past this; without bounding, CREATE TABLE fails with a cryptic
# INVALID_IDENTIFIER and the *entire* discovery aborts.
MAX_IDENTIFIER_LENGTH = 63

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


def bound_name(name: str, max_len: int = MAX_IDENTIFIER_LENGTH) -> str:
    """Deterministically shorten an over-long identifier to ``<= max_len`` chars.

    Keeps a readable prefix and appends a short hash of the *full* name so two
    distinct long names never collapse to the same identifier. Names already
    within the limit are returned unchanged (so this is a no-op for the common
    case and never perturbs existing short column names).
    """
    if len(name) <= max_len:
        return name
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=4).hexdigest()  # 8 hex chars
    keep = max(1, max_len - len(digest) - 1)  # room for "_" + digest
    return f"{name[:keep]}_{digest}"


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
