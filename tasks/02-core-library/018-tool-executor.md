# 018 — Tool Executor

**Sprint**: 1 | **Estimate**: 4h | **Depends on**: 017, 009, 012, 013, 014

## What it does

For each tool call:
1. Look up which `source_ids` the tool needs
2. Fetch **only those sources** (REST, DB, or file) in parallel
3. Ingest each fetched result into in-memory SQLite as a table named after the source's `id`
4. Run the tool's SQL against the combined SQLite DB
5. Apply response shape (field filter, rename, max_rows)
6. Return `ToolResult`

This is what enables cross-source JOINs. A tool that lists `source_ids: ["products_api", "inventory_db"]` gets both ingested into the same SQLite, so its SQL can do:

```sql
SELECT p.name, i.quantity
FROM products_api p
JOIN inventory_db i ON p.id = i.product_id
```

## File to Create

### `packages/core/src/elliot_core/tools/executor.py`

```python
import asyncio
import time
from typing import Any

import structlog

from elliot_core.errors import ElliotError, SourceFetchError, ToolNotFoundError
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.tool import ToolDefinition, ToolResult

log = structlog.get_logger(__name__)


class ToolExecutor:
    """
    Executes a tool against its declared sources.
    One executor instance per connector — holds the source fetcher map.
    """

    def __init__(self, config: ConnectorConfig, fetcher_factory) -> None:
        self._config = config
        self._source_map = {s.id: s for s in config.sources}
        self._tool_map = {t.id: t for t in config.tools}
        self._fetcher_factory = fetcher_factory  # callable(SourceConfig) → Fetcher

    async def execute(self, tool_id: str, params: dict[str, Any]) -> ToolResult:
        tool = self._tool_map.get(tool_id)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{tool_id}' not found in connector '{self._config.slug}'")

        log.info("tool.call.start", tool_id=tool_id, source_ids=tool.source_ids)
        t0 = time.monotonic()

        bound = _coerce_and_validate(tool, params)

        valid, reason = validate_tool_sql(tool.sql)
        if not valid:
            raise ElliotError("INVALID_SQL", reason)

        # Fetch all required sources in parallel
        fetch_results = await self._fetch_sources(tool.source_ids)

        # Ingest each source into SQLite as a table named after source.id
        engine = SQLiteEngine()
        for source_id, fetch_result in fetch_results.items():
            engine.ingest_table(table_name=source_id, rows=fetch_result.rows)

        # Run the tool SQL
        try:
            rows = engine.query(tool.sql, bound)
        except Exception as exc:
            log.error("tool.sql.failed", tool_id=tool_id, error=str(exc))
            raise ElliotError("SQL_EXECUTION_FAILED", str(exc)) from exc

        latency_ms = (time.monotonic() - t0) * 1000
        truncated = len(rows) > tool.response_shape.max_rows
        rows = rows[:tool.response_shape.max_rows]
        rows = _apply_response_shape(rows, tool.response_shape)

        log.info(
            "tool.call.complete",
            tool_id=tool_id,
            rows=len(rows),
            duration_ms=round(latency_ms, 2),
            truncated=truncated,
            sources=list(fetch_results.keys()),
        )

        return ToolResult(
            rows=rows,
            meta={
                "row_count": len(rows),
                "latency_ms": round(latency_ms, 2),
                "truncated": truncated,
                "sources_fetched": list(fetch_results.keys()),
            },
        )

    async def _fetch_sources(
        self, source_ids: list[str]
    ) -> dict[str, Any]:  # source_id → FetchResult
        async def _fetch_one(source_id: str):
            source = self._source_map.get(source_id)
            if source is None:
                raise ElliotError("SOURCE_NOT_FOUND", f"Source '{source_id}' not in connector")
            fetcher = self._fetcher_factory(source)
            try:
                log.debug("source.fetch.start", source_id=source_id, type=source.type)
                result = await fetcher.fetch()
                log.debug("source.fetch.complete", source_id=source_id, rows=len(result.rows))
                return source_id, result
            except Exception as exc:
                log.error("source.fetch.failed", source_id=source_id, error=str(exc))
                raise SourceFetchError(source_id, str(exc)) from exc

        pairs = await asyncio.gather(*[_fetch_one(sid) for sid in source_ids])
        return dict(pairs)


def _coerce_and_validate(tool: ToolDefinition, params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for p in tool.parameters:
        val = params.get(p.name)
        if val is None and p.default is not None:
            val = p.default
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
            raise ElliotError("INVALID_PARAM_TYPE", f"Cannot convert {val!r} to integer")
    if typ == "number":
        return float(val)
    if typ == "boolean":
        return bool(val)
    return str(val)


def _apply_response_shape(rows: list[dict], shape) -> list[dict]:
    if shape.fields:
        rows = [{k: v for k, v in row.items() if k in shape.fields} for row in rows]
    if shape.rename:
        rows = [{shape.rename.get(k, k): v for k, v in row.items()} for row in rows]
    return rows
```

## Done When
- [ ] A tool with `source_ids: ["a", "b"]` fetches both sources in parallel
- [ ] Each source is ingested as a SQLite table named after its `id`
- [ ] A SQL JOIN across two source tables returns correct results
- [ ] Unknown `source_id` raises `ElliotError("SOURCE_NOT_FOUND")`
- [ ] Missing required param raises `ElliotError("MISSING_PARAM")`
- [ ] `max_rows` truncation sets `truncated: true` in meta
- [ ] `response_shape.fields` filters columns
- [ ] All fetch errors are logged with `source_id` and re-raised as `SourceFetchError`

## Tests

```python
import pytest
from unittest.mock import AsyncMock
from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig

def make_config(source_ids_per_tool):
    # helper to build a minimal ConnectorConfig
    ...

async def test_single_source_tool():
    # fetches one source, returns rows
    ...

async def test_cross_source_join():
    # two sources ingested as separate tables, JOIN returns merged rows
    config = make_config(["products", "inventory"])
    executor = ToolExecutor(config, mock_fetcher_factory)
    result = await executor.execute("list_with_stock", {})
    assert result.rows[0].keys() >= {"name", "quantity"}
    assert result.meta["sources_fetched"] == ["products", "inventory"]

async def test_unknown_tool_raises():
    with pytest.raises(ToolNotFoundError):
        await executor.execute("nonexistent", {})

async def test_source_fetch_failure_raises():
    # one source fails — whole call fails with SourceFetchError
    ...

async def test_missing_required_param():
    with pytest.raises(ElliotError, match="MISSING_PARAM"):
        await executor.execute("get_product", {})  # missing required 'id'
```
