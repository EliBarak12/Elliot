from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from elliot_core.errors import ElliotError, SourceFetchError
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.types.source import FetchResult, SourceConfig


def _resolve_dsn(config: SourceConfig, secrets: dict[str, str]) -> str:
    url = config.url or ""
    if url.startswith("{{ env:") and url.endswith(" }}"):
        import os

        env_var = url[7:-3].strip()
        url = secrets.get(env_var) or os.environ.get(env_var, "")
    return url


def _quote_table(name: str, *, dialect: str) -> str:
    """Quote a table identifier using the dialect's identifier quote.

    Postgres + SQLite use double-quotes; MySQL/MariaDB use backticks. The
    quote character also serves as the escape mechanism — doubling it
    embeds a literal quote — so we apply that defensively even though
    Elliot's tool registry won't usually accept identifiers containing
    one.
    """
    if dialect == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def query_database(config: SourceConfig, secrets: dict[str, str]) -> FetchResult:
    sql = config.query
    if not sql:
        if config.table:
            sql = f"SELECT * FROM {_quote_table(config.table, dialect=config.type)}"
        else:
            raise ElliotError("INVALID_TOOL", f"Source '{config.id}' has no query or table")

    valid, reason = validate_tool_sql(sql)
    if not valid:
        raise ElliotError("INVALID_SQL", f"Source '{config.id}': {reason}")

    rows = _run_query(config, sql, secrets)
    return FetchResult(
        rows=rows,
        fetched_at=datetime.now(UTC).isoformat(),
    )


def run_select(
    config: SourceConfig,
    secrets: dict[str, str],
    sql: str,
    params: dict[str, Any] | None = None,
) -> FetchResult:
    """Run a validated, parameterized SELECT against a DB source.

    The connector runtime uses this to push a tool's compiled WHERE /
    ORDER BY / LIMIT straight to Postgres/MySQL — so the database does the
    filtering and only matching rows cross the wire — instead of fetching
    the whole table and filtering the in-memory SQLite mirror. ``sql`` must
    be a single SELECT (enforced by :func:`validate_tool_sql`); ``params``
    are bound, never interpolated.
    """
    valid, reason = validate_tool_sql(sql)
    if not valid:
        raise ElliotError("INVALID_SQL", f"Source '{config.id}': {reason}")
    rows = _run_query(config, sql, secrets, params)
    return FetchResult(rows=rows, fetched_at=datetime.now(UTC).isoformat())


def _run_query(
    config: SourceConfig,
    sql: str,
    secrets: dict[str, str],
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise ElliotError("MISSING_DEPENDENCY", "sqlalchemy is required for DB sources") from exc

    dsn = _resolve_dsn(config, secrets)
    if not dsn:
        raise ElliotError("INVALID_TOOL", f"Source '{config.id}' has no connection URL")

    connect_args: dict[str, Any] = {}
    if config.type == "postgres":
        # Enforce read-only at the connection level: any write or DDL the
        # validator missed will be rejected by Postgres itself. MySQL has no
        # session-level read-only equivalent, so it relies on validate_tool_sql.
        connect_args["options"] = "-c statement_timeout=30000 -c default_transaction_read_only=on"

    try:
        engine = create_engine(dsn, connect_args=connect_args, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return [dict(row._mapping) for row in result]
    except ElliotError:
        raise
    except Exception as exc:
        raise SourceFetchError(
            f"Query failed on source '{config.id}': {type(exc).__name__}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            engine.dispose()
