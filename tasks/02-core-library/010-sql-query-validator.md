# 010 — SQL Query Validator

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 009

## Objective
Prevent SQL injection and DDL execution. All tool SQL goes through this.

## Files to Create

### `packages/core/src/elliot_core/sqlite/query_runner.py`
```python
import re
from typing import Any
from elliot_core.errors import ElliotError

DDL_PATTERN = re.compile(
    r"\b(DROP|CREATE|ALTER|INSERT|UPDATE|DELETE|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)

def validate_tool_sql(sql: str) -> tuple[bool, str]:
    """
    Returns (True, "") if valid SELECT, or (False, reason) if not.
    """
    stripped = sql.strip()
    # Remove single-line comments before checking
    no_comments = re.sub(r"--[^\n]*", "", stripped).strip()

    if not no_comments:
        return False, "SQL is empty"
    if not no_comments.upper().startswith("SELECT"):
        return False, "SQL must start with SELECT"
    if ";" in no_comments:
        return False, "Multiple statements not allowed"
    match = DDL_PATTERN.search(no_comments)
    if match:
        return False, f"Forbidden keyword: {match.group()}"
    return True, ""

def run_tool_query(
    engine: "SQLiteEngine",  # type: ignore[name-defined]
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    valid, reason = validate_tool_sql(sql)
    if not valid:
        raise ElliotError("INVALID_SQL", reason)
    return engine.query(sql, params or {})
```

## Done When
- [ ] `validate_tool_sql("SELECT * FROM t")` returns `(True, "")`
- [ ] `validate_tool_sql("DROP TABLE t")` returns `(False, ...)`
- [ ] `validate_tool_sql("SELECT 1; DROP TABLE t")` returns `(False, ...)` (semicolon)
- [ ] `validate_tool_sql("SELECT * FROM t -- ; DROP TABLE t")` returns `(True, "")` (comment stripped)
- [ ] `validate_tool_sql("PRAGMA table_info(t)")` returns `(False, ...)`
