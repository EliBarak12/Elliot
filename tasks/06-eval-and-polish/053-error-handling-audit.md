# 053 — Error Handling Audit

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 052

## Objective
Ensure every error path in the system surfaces a clean, user-readable message. No raw stack traces to agents.

## What to Do

### Plugin MCP tool handlers
Every tool handler must have a top-level try/except:
```python
try:
    # ... tool logic
except Exception as err:
    return to_mcp_error_content(err)
```
Verify this pattern exists in: `source_tools.py`, `sql_tools.py`, `tool_tools.py`, `skill_tools.py`, `context_tools.py`, `connector_tools.py`, `studio_tools.py`.

### Runtime executor
- `execute()` wraps all errors as `ElliotError` before re-raising
- SQLite errors include the column/table name in the message

### Core library
- No raw exception messages leak from sqlite3 — wrap with `ElliotError('INVALID_SQL', err_msg)`
- All `except Exception` blocks use `is_elliot_error(err)` to decide whether to wrap or re-raise

## Done When
- [ ] Every MCP tool handler has try/except returning `to_mcp_error_content`
- [ ] No bare `Exception` raised from tool handlers (only `ElliotError`)
- [ ] A bad SQL query returns a readable message, not a raw sqlite3 error
