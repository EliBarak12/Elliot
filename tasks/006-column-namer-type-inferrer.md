# 006 — Column Namer + Type Inferrer

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005

## Objective
Two small utilities used by the JSON flattener.

## Files to Create

### `packages/core/src/elliot_core/sqlite/column_namer.py`
```python
import re

SQL_RESERVED = frozenset({
    "select", "from", "where", "group", "order", "limit", "index",
    "table", "create", "drop", "insert", "update", "delete", "join",
    "on", "as", "by", "and", "or", "not", "null", "is", "in", "values",
})

def safe_name(raw: str) -> str:
    """Convert arbitrary string to a safe SQLite column name."""
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
```

### `packages/core/src/elliot_core/sqlite/type_inferrer.py`
```python
import re
from typing import Any
from elliot_core.types.sqlite import ColumnMeta

def infer_column_type(samples: list[Any]) -> str:
    """Return 'INTEGER', 'REAL', or 'TEXT' based on majority vote."""
    non_null = [s for s in samples if s is not None]
    if not non_null:
        return "TEXT"
    if all(isinstance(v, bool) for v in non_null):
        return "INTEGER"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        if all(abs(v) <= 2**53 for v in non_null):
            return "INTEGER"
        return "TEXT"  # too large for JS-safe int
    if all(isinstance(v, float | int) and not isinstance(v, bool) for v in non_null):
        return "REAL"
    return "TEXT"

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[\d:.Z+-]+)?$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

def detect_format(value: str) -> str | None:
    if ISO_DATE_RE.match(value):
        return "iso_date"
    if UUID_RE.match(value):
        return "uuid"
    if EMAIL_RE.match(value):
        return "email"
    if value.lower() in ("true", "false"):
        return "boolean_string"
    return None
```

## Done When
- [ ] `safe_name("from")` returns `"from_col"`
- [ ] `safe_name("user-id")` returns `"user_id"`
- [ ] `infer_column_type([1, 2, 3])` returns `"INTEGER"`
- [ ] `infer_column_type([True, False])` returns `"INTEGER"`
- [ ] `infer_column_type([1.5, 2])` returns `"REAL"`
