"""DB and file source schema introspection for the agentic builder."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    row_count_estimate: int | None = None


async def inspect_db_source(source: Any) -> TableSchema:
    """Introspect a postgres source — returns column schema and 3 sample rows."""
    import asyncpg

    url: str = source.url or ""
    table: str = getattr(source, "table", "") or ""

    log.info("schema.inspect.start", source_id=source.id, type=source.type)
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
            """,
            table,
        )
        columns = [
            ColumnInfo(
                name=r["column_name"],
                type=r["data_type"],
                nullable=r["is_nullable"] == "YES",
            )
            for r in rows
        ]
        sample = await conn.fetch(f"SELECT * FROM {table} LIMIT 3")  # noqa: S608
        sample_rows = [dict(r) for r in sample]
        count_row = await conn.fetchrow(
            "SELECT reltuples::bigint FROM pg_class WHERE relname = $1", table
        )
        row_count: int | None = int(count_row[0]) if count_row else None
    finally:
        await conn.close()

    log.info("schema.inspect.complete", source_id=source.id, columns=len(columns))
    return TableSchema(
        source_id=source.id,
        table_name=table,
        columns=columns,
        sample_rows=sample_rows,
        row_count_estimate=row_count,
    )


async def inspect_file_source(source: Any, fetcher_factory: Any) -> TableSchema:
    """Load a small sample from a file source to infer schema."""
    fetcher = fetcher_factory(source)
    result = await fetcher.fetch()
    rows = result.rows[:3]
    if not rows:
        return TableSchema(
            source_id=source.id,
            table_name=getattr(source, "path", "") or "",
            row_count_estimate=0,
        )
    columns = [ColumnInfo(name=k, type=_infer_type(v)) for k, v in rows[0].items()]
    return TableSchema(
        source_id=source.id,
        table_name=getattr(source, "path", "") or "",
        columns=columns,
        sample_rows=rows,
        row_count_estimate=len(result.rows),
    )


def _infer_type(val: Any) -> str:
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "number"
    return "string"


def schema_to_dict(schema: TableSchema) -> dict[str, Any]:
    """Convert a TableSchema to a JSON-serialisable dict."""
    return {
        "source_id": schema.source_id,
        "table": schema.table_name,
        "columns": [
            {"name": c.name, "type": c.type, "nullable": c.nullable} for c in schema.columns
        ],
        "sample_rows": schema.sample_rows,
        "row_count_estimate": schema.row_count_estimate,
    }
