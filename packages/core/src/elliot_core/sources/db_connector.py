from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from elliot_core.errors import ElliotError, SourceFetchError
from elliot_core.secrets import _PLACEHOLDER, SecretResolutionError, host_env_secrets_allowed
from elliot_core.sql import safe_ident
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.types.source import FetchResult, SourceConfig

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# SQLAlchemy Engines are designed to be long-lived: they own a connection pool
# and a per-statement compiled-SQL cache. Creating/disposing one per query
# discards both. Cache them keyed by (dsn, dialect); Engines are thread-safe.
_engine_cache: dict[tuple[str, str], Engine] = {}
_engine_cache_lock = threading.Lock()


def _resolve_dsn(config: SourceConfig, secrets: dict[str, str]) -> str:
    """Resolve the source's connection URL, expanding a ``{{ env:VAR }}`` placeholder.

    Only the strict placeholder grammar (:data:`elliot_core.secrets._PLACEHOLDER`,
    uppercase name, no space after the colon) is expanded — a loose look-alike
    such as ``{{ env: DATABASE_URL }}`` is treated as a literal (broken) DSN,
    never resolved from the host environment. Resolution consults the supplied
    ``secrets`` map first and falls back to ``os.environ`` only when
    :func:`~elliot_core.secrets.host_env_secrets_allowed` permits it — the
    multi-tenant cloud sets ``ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS=1`` so a tenant
    connector can never read the platform's own ``DATABASE_URL``.
    """
    url = config.url or ""
    match = _PLACEHOLDER.fullmatch(url)
    if match:
        env_var = match.group(1)
        resolved = secrets.get(env_var)
        if resolved:
            return resolved
        if host_env_secrets_allowed():
            import os

            resolved = os.environ.get(env_var)
            if resolved:
                return resolved
        raise SecretResolutionError(env_var)
    return url


def _quote_table(name: str, *, dialect: str) -> str:
    """Validate and quote a table identifier for the dialect.

    The name is routed through :func:`elliot_core.sql.safe_ident` — the single
    origin for identifier interpolation — which raises the standard
    ``INVALID_IDENTIFIER`` error on anything that is not a plain identifier
    (quotes, whitespace, ``;``, leading digit, over-long). Postgres + SQLite
    use the returned double-quoted form; MySQL/MariaDB use backticks around
    the already-validated name.
    """
    quoted = safe_ident(name)
    if dialect == "mysql":
        return f"`{name}`"
    return quoted


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


def _get_engine(dsn: str, dialect: str) -> Engine:
    """Return a cached SQLAlchemy Engine for ``dsn``, creating one if needed."""
    from sqlalchemy import create_engine

    key = (dsn, dialect)
    with _engine_cache_lock:
        engine = _engine_cache.get(key)
        if engine is not None:
            return engine

        connect_args: dict[str, Any] = {}
        if dialect == "postgres":
            # Enforce read-only at the connection level: any write or DDL the
            # validator missed is rejected by Postgres itself.
            connect_args["options"] = (
                "-c statement_timeout=30000 -c default_transaction_read_only=on"
            )
        elif dialect == "mysql":
            # MySQL 5.6.5+ supports session read-only transactions. ``init_command``
            # runs on every new pooled connection, so a write/DDL the validator
            # missed is rejected by MySQL itself — defence-in-depth matching
            # Postgres, not validator-only. DB sources are read-only by design
            # (mutations go through REST api_mapping), so this is safe.
            connect_args["init_command"] = "SET SESSION TRANSACTION READ ONLY"
        engine = create_engine(dsn, connect_args=connect_args, pool_pre_ping=True)
        _engine_cache[key] = engine
        return engine


def _run_query(
    config: SourceConfig,
    sql: str,
    secrets: dict[str, str],
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import text
    except ImportError as exc:
        raise ElliotError("MISSING_DEPENDENCY", "sqlalchemy is required for DB sources") from exc

    dsn = _resolve_dsn(config, secrets)
    if not dsn:
        raise ElliotError("INVALID_TOOL", f"Source '{config.id}' has no connection URL")

    try:
        engine = _get_engine(dsn, config.type)
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return [dict(row._mapping) for row in result]
    except ElliotError:
        raise
    except Exception as exc:
        raise SourceFetchError(
            f"Query failed on source '{config.id}': {type(exc).__name__}"
        ) from exc
