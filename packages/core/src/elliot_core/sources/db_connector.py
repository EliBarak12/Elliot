from __future__ import annotations

from datetime import datetime, timezone
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


def query_database(config: SourceConfig, secrets: dict[str, str]) -> FetchResult:
    sql = config.query
    if not sql:
        if config.table:
            sql = f'SELECT * FROM "{config.table}"'
        else:
            raise ElliotError("INVALID_TOOL", f"Source '{config.id}' has no query or table")

    valid, reason = validate_tool_sql(sql)
    if not valid:
        raise ElliotError("INVALID_SQL", f"Source '{config.id}': {reason}")

    rows = _run_query(config, sql, secrets)
    return FetchResult(
        rows=rows,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def _run_query(config: SourceConfig, sql: str, secrets: dict[str, str]) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise ElliotError("MISSING_DEPENDENCY", "sqlalchemy is required for DB sources") from exc

    dsn = _resolve_dsn(config, secrets)
    if not dsn:
        raise ElliotError("INVALID_TOOL", f"Source '{config.id}' has no connection URL")

    connect_args: dict[str, Any] = {}
    if config.type == "postgres":
        connect_args["options"] = "-c statement_timeout=30000"

    try:
        engine = create_engine(dsn, connect_args=connect_args, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            return [dict(row._mapping) for row in result]
    except ElliotError:
        raise
    except Exception as exc:
        raise SourceFetchError(
            f"Query failed on source '{config.id}': {type(exc).__name__}"
        ) from exc
    finally:
        try:
            engine.dispose()  # type: ignore[possibly-undefined]
        except Exception:
            pass
