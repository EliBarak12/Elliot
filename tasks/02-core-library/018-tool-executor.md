# 018 — Tool Executor

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 017, 009

## Files to Create

### `packages/core/src/elliot_core/tools/executor.py`
```python
import time
from typing import Any
from elliot_core.types.tool import ToolDefinition, ToolResult
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.errors import ElliotError

def execute_tool(
    tool: ToolDefinition,
    params: dict[str, Any],
    engine: SQLiteEngine,
) -> ToolResult:
    bound = _coerce_and_validate(tool, params)
    valid, reason = validate_tool_sql(tool.sql)
    if not valid:
        raise ElliotError("INVALID_SQL", reason)
    start = time.monotonic()
    rows = engine.query(tool.sql, bound)
    latency_ms = (time.monotonic() - start) * 1000
    truncated = len(rows) > tool.response_shape.max_rows
    rows = rows[:tool.response_shape.max_rows]
    rows = _apply_response_shape(rows, tool.response_shape)
    return ToolResult(
        rows=rows,
        meta={"row_count": len(rows), "latency_ms": latency_ms, "truncated": truncated},
    )

def _coerce_and_validate(tool: ToolDefinition, params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for p in tool.parameters:
        val = params.get(p.name)
        if val is None and p.default is not None:
            val = p.default
        if val is None and p.required:
            raise ElliotError("MISSING_PARAM", f"Required parameter missing: {p.name}")
        if val is not None:
            result[p.name] = _coerce(val, p.type)
    return result

def _coerce(val: Any, typ: str) -> Any:
    if typ == "integer":
        try:
            return int(val)
        except (ValueError, TypeError):
            raise ElliotError("INVALID_PARAM_TYPE", f"Cannot convert {val!r} to integer")
    if typ == "number":
        return float(val)
    if typ == "boolean":
        return bool(val)
    return str(val)

def _apply_response_shape(rows: list[dict], shape: Any) -> list[dict]:
    if shape.fields:
        rows = [{k: v for k, v in row.items() if k in shape.fields} for row in rows]
    if shape.rename:
        rows = [{shape.rename.get(k, k): v for k, v in row.items()} for row in rows]
    return rows
```

## Done When
- [ ] `"42"` coerced to `42` for integer param
- [ ] Missing required param raises `ElliotError("MISSING_PARAM")`
- [ ] `max_rows` truncation sets `truncated: True` in meta
- [ ] `response_shape.fields` filters columns correctly
