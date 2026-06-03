# Task 077 — DB Schema Introspection

## Goal
Add a `inspect_source_schema(source_id)` tool to the agentic builder MCP tools (task 071) so an agent can discover what tables and columns exist in a DB or file source before proposing filters and return fields.

## Why
The agentic builder needs to know the schema before it can help the user define tools. Without this, the agent is proposing field names blind. For a Postgres source it should be able to say: “I see a `users` table with columns: `id` (integer), `email` (text), `created_at` (timestamp), `plan` (text)”.

## Implementation

### `packages/core/src/elliot_core/tools/schema_inspector.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import structlog

log = structlog.get_logger(__name__)

@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True

@dataclass
class TableSchema:
    source_id: str
    table_name: str
    columns: list[ColumnInfo]
    sample_rows: list[dict[str, Any]]
    row_count_estimate: int | None


async def inspect_db_source(source) -> TableSchema:
    """Introspect a postgres/mysql source — returns schema + 3 sample rows."""
    import asyncpg  # postgres
    url = source.url
    table = source.table or "(subquery)"

    log.info("schema.inspect.start", source_id=source.id, type=source.type)
    conn = await asyncpg.connect(url)
    try:
        # Get columns from information_schema
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
            """,
            source.table,
        )
        columns = [
            ColumnInfo(name=r["column_name"], type=r["data_type"],
                       nullable=r["is_nullable"] == "YES")
            for r in rows
        ]
        # Sample rows
        sample = await conn.fetch(f'SELECT * FROM {source.table} LIMIT 3')
        sample_rows = [dict(r) for r in sample]
        # Row count estimate
        count_row = await conn.fetchrow(
            "SELECT reltuples::bigint FROM pg_class WHERE relname = $1", source.table
        )
        row_count = int(count_row[0]) if count_row else None
    finally:
        await conn.close()

    log.info("schema.inspect.complete", source_id=source.id, columns=len(columns))
    return TableSchema(source_id=source.id, table_name=table,
                       columns=columns, sample_rows=sample_rows,
                       row_count_estimate=row_count)


async def inspect_file_source(source, fetcher_factory) -> TableSchema:
    """Load a small sample from a file source to infer schema."""
    fetcher = fetcher_factory(source)
    result = await fetcher.fetch()
    rows = result.rows[:3]
    if not rows:
        return TableSchema(source_id=source.id, table_name=source.path or "",
                           columns=[], sample_rows=[], row_count_estimate=0)
    columns = [
        ColumnInfo(name=k, type=_infer_type(v))
        for k, v in rows[0].items()
    ]
    return TableSchema(source_id=source.id, table_name=source.path or "",
                       columns=columns, sample_rows=rows,
                       row_count_estimate=len(result.rows))


def _infer_type(val: Any) -> str:
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    return "string"
```

### Add to agentic builder tools (task 071)

```python
def inspect_source_schema(draft_id: str, source_id: str) -> dict:
    """
    Inspect the schema of a source: returns column names, types, and 3 sample rows.
    Use this BEFORE proposing filter_groups and return_fields for a tool,
    so you can suggest real column names to the user.
    Also use for file sources (CSV, JSON) to see the available fields.
    """
    source = source_map.get(source_id)
    if not source:
        return {"error": f"Source '{source_id}' not found"}
    if source.type in ("postgres", "mysql"):
        schema = asyncio.run(inspect_db_source(source))
    elif source.type == "file":
        schema = asyncio.run(inspect_file_source(source, fetcher_factory))
    else:  # rest
        return {"note": "REST sources don’t have a fixed schema. Use preview_source to see sample data."}
    return {
        "source_id": schema.source_id,
        "table": schema.table_name,
        "columns": [{"name": c.name, "type": c.type, "nullable": c.nullable} for c in schema.columns],
        "sample_rows": schema.sample_rows,
        "row_count_estimate": schema.row_count_estimate,
    }
```

## Estimate
4–5 hours
