# 018 — Tool Executor

**Sprint**: 1 | **Estimate**: 5h | **Depends on**: 017, 009, 012, 013, 014

## What it does

The executor handles two execution paths depending on the tool and source type:

**Path A — READ (DB / file sources):**
1. For each `source_id` in the tool: fetch data (DB query or file read) in parallel
2. Ingest each result into in-memory SQLite as a table named after `source.id`
3. Generate a safe parameterized SELECT from `filter_groups` + `return_fields` + `limit`
4. Run it, apply `response_shape`, return `ToolResult`

**Path B — WRITE / ACTION (REST sources):**
1. Validate and coerce parameters
2. Build the HTTP request from `api_mapping` (path, query params, body)
3. Execute via `httpx`
4. Return the response as `ToolResult`

**The agent never writes SQL or HTTP request details.** That is entirely Elliot’s job.

## File to Create

### `packages/core/src/elliot_core/tools/executor.py`

```python
import asyncio
import time
from typing import Any

import structlog

from elliot_core.errors import ElliotError, SourceFetchError, ToolNotFoundError
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.tools.query_builder import build_select_sql
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.tool import ToolDefinition, ToolResult

log = structlog.get_logger(__name__)


class ToolExecutor:
    def __init__(self, config: ConnectorConfig, fetcher_factory) -> None:
        self._config = config
        self._source_map = {s.id: s for s in config.sources}
        self._tool_map = {t.id: t for t in config.tools}
        self._fetcher_factory = fetcher_factory

    async def execute(self, tool_id: str, params: dict[str, Any]) -> ToolResult:
        tool = self._tool_map.get(tool_id)
        if not tool:
            raise ToolNotFoundError(f"Tool '{tool_id}' not found")

        log.info("tool.call.start", tool_id=tool_id, category=tool.category)
        t0 = time.monotonic()
        bound = _coerce_and_validate(tool, params)

        if tool.category == "READ":
            result = await self._execute_read(tool, bound)
        else:
            result = await self._execute_write(tool, bound)

        latency_ms = (time.monotonic() - t0) * 1000
        log.info("tool.call.complete", tool_id=tool_id,
                 rows=len(result.rows), duration_ms=round(latency_ms, 2))
        return result

    async def _execute_read(self, tool: ToolDefinition, params: dict) -> ToolResult:
        # Fetch all required sources in parallel
        fetch_results = await self._fetch_sources(tool.source_ids)

        # Ingest into SQLite — each source becomes a table named after source.id
        engine = SQLiteEngine()
        for source_id, fetch_result in fetch_results.items():
            engine.ingest_table(table_name=source_id, rows=fetch_result.rows)

        # Generate and run SELECT
        sql, sql_params = build_select_sql(tool, params)
        try:
            rows = engine.query(sql, sql_params)
        except Exception as exc:
            log.error("tool.sql.failed", tool_id=tool.id, error=str(exc))
            raise ElliotError("SQL_EXECUTION_FAILED", str(exc)) from exc

        truncated = len(rows) > tool.response_shape.max_rows
        rows = rows[:tool.response_shape.max_rows]
        rows = _apply_rename(rows, tool.response_shape.rename)

        return ToolResult(
            rows=rows,
            meta={"row_count": len(rows), "truncated": truncated,
                  "sources_fetched": list(fetch_results.keys())},
        )

    async def _execute_write(self, tool: ToolDefinition, params: dict) -> ToolResult:
        """For REST WRITE / ACTION tools: build and execute an HTTP call."""
        if not tool.api_mapping:
            raise ElliotError("MISSING_API_MAPPING",
                              f"WRITE tool '{tool.id}' has no api_mapping")
        source = self._source_map.get(tool.source_ids[0])
        if not source:
            raise ElliotError("SOURCE_NOT_FOUND", f"Source '{tool.source_ids[0]}' not found")

        mapping = tool.api_mapping
        base_url = (source.url or "").rstrip("/")
        path = mapping.path_template or ""

        # Interpolate path params: /users/{user_id} → /users/42
        for name, val in params.items():
            path = path.replace(f"{{{name}}}", str(val))

        url = base_url + path
        query = {k: params[k] for k in mapping.query_params if k in params}
        body = {k: params[k] for k in mapping.body_params if k in params}

        import httpx
        headers = {}
        if source.auth:
            fetcher = self._fetcher_factory(source)
            headers = fetcher.auth_headers()

        try:
            async with httpx.AsyncClient(timeout=source.timeout_ms / 1000) as client:
                resp = await client.request(
                    method=mapping.method,
                    url=url,
                    params=query or None,
                    json=body if mapping.body_format == "json" else None,
                    data=body if mapping.body_format == "form" else None,
                    headers=headers,
                )
            resp.raise_for_status()
            data = resp.json()
            rows = data if isinstance(data, list) else [data]
        except httpx.HTTPStatusError as exc:
            log.error("tool.write.http_error", tool_id=tool.id,
                      status=exc.response.status_code, url=url)
            raise ElliotError("API_REQUEST_FAILED",
                              f"API returned {exc.response.status_code}: {exc.response.text[:200]}") from exc
        except Exception as exc:
            log.error("tool.write.failed", tool_id=tool.id, error=str(exc))
            raise ElliotError("API_REQUEST_FAILED", str(exc)) from exc

        return ToolResult(rows=rows, meta={"row_count": len(rows), "url": url})

    async def _fetch_sources(self, source_ids: list[str]) -> dict:
        async def _one(sid):
            source = self._source_map.get(sid)
            if not source:
                raise ElliotError("SOURCE_NOT_FOUND", f"Source '{sid}' not in connector")
            try:
                log.debug("source.fetch.start", source_id=sid, type=source.type)
                result = await self._fetcher_factory(source).fetch()
                log.debug("source.fetch.complete", source_id=sid, rows=len(result.rows))
                return sid, result
            except Exception as exc:
                log.error("source.fetch.failed", source_id=sid, error=str(exc))
                raise SourceFetchError(sid, str(exc)) from exc

        pairs = await asyncio.gather(*[_one(sid) for sid in source_ids])
        return dict(pairs)


def _coerce_and_validate(tool: ToolDefinition, params: dict) -> dict:
    result = {}
    for p in tool.parameters:
        val = params.get(p.name, p.default)
        if val is None and p.required:
            raise ElliotError("MISSING_PARAM", f"Required parameter missing: '{p.name}'")
        if val is not None:
            result[p.name] = _coerce(val, p.type)
    return result


def _coerce(val: Any, typ: str) -> Any:
    if typ == "integer":
        try:
            return int(val)
        except (ValueError, TypeError):
            raise ElliotError("INVALID_PARAM_TYPE", f"Expected integer, got: {val!r}")
    if typ == "number":
        return float(val)
    if typ == "boolean":
        return bool(val)
    return str(val)


def _apply_rename(rows: list[dict], rename: dict) -> list[dict]:
    if not rename:
        return rows
    return [{rename.get(k, k): v for k, v in row.items()} for row in rows]
```

### `packages/core/src/elliot_core/tools/query_builder.py`

```python
from elliot_core.types.tool import ToolDefinition

_OP_MAP = {
    "=": "=", "!=": "!=", ">": ">", ">=": ">=", "<": "<", "<=": "<=",
    "contains": "LIKE", "in_list": "IN",
    "is_null": "IS NULL", "is_not_null": "IS NOT NULL",
}


def build_select_sql(tool: ToolDefinition, params: dict) -> tuple[str, dict]:
    """
    Convert tool.filter_groups + return_fields + limit into a safe
    parameterized SELECT. Returns (sql, bound_params).
    """
    # SELECT
    if not tool.return_fields:
        select_clause = "*"
    else:
        parts = []
        for rf in tool.return_fields:
            col = rf.field.replace(".", "_")  # products_api.name → products_api_name
            if rf.aggregation and rf.aggregation != "none":
                alias = rf.alias or col
                parts.append(f"{rf.aggregation.upper()}({col}) AS {alias}")
            else:
                alias = f" AS {rf.alias}" if rf.alias and rf.alias != col else ""
                parts.append(f"{col}{alias}")
        select_clause = ", ".join(parts)

    # FROM (primary source is first in source_ids)
    primary = tool.source_ids[0]
    sql = f"SELECT {select_clause} FROM {primary}"

    # WHERE
    bound: dict = {}
    where_parts = []
    for group in tool.filter_groups:
        group_parts = []
        for cond in group.conditions:
            col = cond.field.replace(".", "_")
            op = _OP_MAP.get(cond.operator, cond.operator)

            if cond.operator in ("is_null", "is_not_null"):
                group_parts.append(f"{col} {op}")
            elif cond.parameter_name:
                val = params.get(cond.parameter_name)
                if val is None:
                    continue  # optional parameter not provided — skip condition
                key = f"p_{cond.parameter_name}"
                if cond.operator == "contains":
                    bound[key] = f"%{val}%"
                    group_parts.append(f"{col} LIKE :{key}")
                elif cond.operator == "in_list":
                    # SQLite doesn’t support list params — inline as comma list
                    vals = val if isinstance(val, list) else val.split(",")
                    placeholders = ", ".join(f":{key}_{i}" for i, _ in enumerate(vals))
                    for i, v in enumerate(vals):
                        bound[f"{key}_{i}"] = v
                    group_parts.append(f"{col} IN ({placeholders})")
                else:
                    bound[key] = val
                    group_parts.append(f"{col} {op} :{key}")
            elif cond.value is not None:
                key = f"fixed_{col}"
                bound[key] = cond.value
                group_parts.append(f"{col} {op} :{key}")

        if group_parts:
            joined = f" {group.logic} ".join(group_parts)
            where_parts.append(f"({joined})")

    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    sql += f" LIMIT {tool.limit}"
    return sql, bound
```

## Done When
- [ ] READ tool with `filter_groups` generates correct parameterized SQL
- [ ] READ tool with multiple `source_ids` fetches both in parallel and JOINs via SQLite
- [ ] WRITE tool with `api_mapping` makes the correct HTTP call with params in body/query/path
- [ ] Optional filter condition (parameter not provided) is skipped silently
- [ ] `in_list` operator works with comma-separated string input
- [ ] `contains` operator generates `LIKE %value%`
- [ ] Missing required param raises `ElliotError("MISSING_PARAM")`
- [ ] HTTP error from WRITE tool raises `ElliotError("API_REQUEST_FAILED")` with status code
- [ ] All fetch/exec errors logged with `source_id` / `tool_id`
