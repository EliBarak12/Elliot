# 007 — JSON Flattener

**Sprint**: 1 | **Estimate**: 4h | **Depends on**: 006

## Objective
Turn arbitrary nested JSON into flat SQLite-ready tables.

## Files to Create

### `packages/core/src/elliot_core/sqlite/flattener.py`

```python
from elliot_core.types.sqlite import FlattenedTable, FlattenResult, FlattenWarning, ColumnMeta
from elliot_core.sqlite.column_namer import safe_name, deduplicate_names
from elliot_core.sqlite.type_inferrer import infer_column_type
from typing import Any

MAX_DEPTH = 5
MAX_ARRAY_ROWS = 1000

def flatten(data: list[Any], table_name: str) -> FlattenResult:
    """Flatten a list of JSON objects into SQLite-ready tables."""
    ...
```

**Rules to implement (all required):**
1. Primitive field → column in current table
2. Nested object → flatten inline with `parent_child` key (underscore separator)
3. Array of primitives → serialize as JSON TEXT column
4. Array of objects → child table `<parent>_<key>`, add `_parent_id` INTEGER, `_index` INTEGER
5. Depth > `MAX_DEPTH` (5) → serialize as TEXT, emit `FlattenWarning(type="depth_exceeded", ...)`
6. Circular reference (use `id()` set of visited object ids per branch) → serialize as TEXT `"[Circular]"`, emit warning
7. `bool` → `1` or `0` (INTEGER)
8. `None` → keep as Python `None` (maps to SQL NULL)
9. `int` > 2·53 → convert to `str` (TEXT)
10. Column names → run through `safe_name()` then `deduplicate_names()`
11. Array length > `MAX_ARRAY_ROWS` → truncate, emit `FlattenWarning(type="array_truncated", ...)`
12. Empty array → create empty child table (schema inferred from first non-empty sibling row if any)

**Type inference**: after collecting all rows, call `infer_column_type(samples)` on each column's values to set `ColumnMeta.sqlite_type`.

## Done When
- [ ] All 12 rules implemented
- [ ] Returns correct `FlattenResult` with `related_tables` for nested arrays
- [ ] `uv run mypy packages/core/src` still exits 0
