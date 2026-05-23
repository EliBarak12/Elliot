"""Execute ToolDefinition calls against live data sources."""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

import jmespath
import structlog

from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
from elliot_core.tools.query_builder import build_select_sql
from elliot_core.types import (
    AuthConfig,
    ConnectorConfig,
    QueryResult,
    SourceConfig,
    ToolDefinition,
)

log = structlog.get_logger(__name__)


class ExecutorError(Exception):
    pass


# Bug: Studio's `elliot_discover_source` flattens a source into a primary
# table named `<source.table_name>` plus child tables named
# `<source.table_name>_<field>[_...]`. Connector tools authored against
# those names used to fail in the runtime because the executor only ever
# ingested a single flat table keyed by `source.id`, never running the
# flattener. This module now mirrors the discover path: each source is
# fetched, flattened, and loaded into a long-lived per-executor engine.
_DEFAULT_TTL_SECONDS = 300

# Hard cap on rows materialized into a single tool result. A tool whose SQL
# omits a LIMIT could otherwise return an entire table and OOM the worker /
# blow the agent's context window. Configurable via ELLIOT_MAX_RESULT_ROWS.
_DEFAULT_MAX_RESULT_ROWS = 10_000


def max_result_rows() -> int:
    """Hard cap on rows returned per tool call (env ELLIOT_MAX_RESULT_ROWS)."""
    raw = os.environ.get("ELLIOT_MAX_RESULT_ROWS", "")
    try:
        return max(1, int(raw)) if raw else _DEFAULT_MAX_RESULT_ROWS
    except ValueError:
        return _DEFAULT_MAX_RESULT_ROWS


class ToolExecutor:
    """
    Executes a ToolDefinition against the connector's live data sources.

    Sources are fetched, flattened, and loaded into a cached in-memory
    SQLiteEngine so that connector-authored SQL (which references the
    flattener's table names — `<source>` plus `<source>_<field>` for
    nested arrays/objects) resolves against tables that actually exist.

    The cache is bounded by a TTL; once a source's data is older than the
    TTL the next tool call re-fetches and reloads it. Tests inject a
    pre-loaded engine via the `engine` kwarg to skip materialization.
    """

    def __init__(
        self,
        config: ConnectorConfig,
        secrets: dict[str, str],
        engine: SQLiteEngine | None = None,
        materialization_ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._sources: dict[str, SourceConfig] = {s.id: s for s in config.sources}
        self._injected_engine = engine
        self._engine: SQLiteEngine | None = engine
        # source_id -> monotonic timestamp of last successful materialization
        self._materialized_at: dict[str, float] = {}
        self._ttl = max(0.0, materialization_ttl_seconds)
        # One lock per source_id so concurrent tool calls serialize the
        # fetch/flatten/load for the same source without blocking unrelated
        # sources.
        self._locks: dict[str, asyncio.Lock] = {}

    async def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> QueryResult:
        from elliot_core.sqlite.query_runner import validate_tool_sql

        # DB filter push-down: when a tool's filters compile to a SELECT and
        # it needs exactly one Postgres/MySQL source, run that SELECT straight
        # against the database so filtering, projection and LIMIT all happen
        # server-side — instead of snapshotting the whole table into SQLite.
        pushdown = self._pushdown_source(tool)
        if pushdown is not None:
            return await self._execute_db_pushdown(tool, pushdown, arguments)

        # Determine SQL: prefer explicit sql, fall back to build_select_sql for filter_groups tools
        if tool.sql:
            # Even connector-supplied SQL must be a single SELECT/CTE — a
            # malicious or buggy connector author cannot ship a DDL/DML tool
            # (CLAUDE.md: "READ tools must not mutate").
            ok, reason = validate_tool_sql(tool.sql)
            if not ok:
                raise ExecutorError(f"Tool {tool.id!r} has invalid SQL: {reason}")
            sql: str = tool.sql
            params: dict[str, Any] = {p.name: arguments.get(p.name) for p in tool.parameters}
        elif tool.filter_groups or tool.return_fields:
            sql, params = build_select_sql(tool, arguments)
        else:
            raise ExecutorError(f"Tool '{tool.id}' has no sql or filter_groups defined")

        # Tests/internals can inject a pre-loaded engine — skip materialization
        # entirely so unit tests don't need network/file fixtures.
        if self._injected_engine is not None:
            rows = self._injected_engine.query(sql, params)
            return self._capped_result(tool.id, rows)

        engine = await self._ensure_materialized(tool, arguments)

        try:
            rows = engine.query(sql, params)
        except Exception as exc:
            from elliot_core.errors import ElliotError

            if isinstance(exc, ElliotError) and exc.code == "INVALID_SQL":
                table_names = engine.get_table_names()
                if not table_names:
                    raise ElliotError(
                        "SOURCE_NOT_MATERIALIZED",
                        (
                            "No data is loaded for this connector. None of the "
                            "configured sources produced rows, so the tool's "
                            "SQL has no tables to query."
                        ),
                        detail={"tool_id": tool.id, "sources": list(self._sources.keys())},
                    ) from exc
                missing = _missing_tables(sql, table_names)
                if missing:
                    raise ElliotError(
                        "TABLE_NOT_FOUND",
                        (
                            f"Tool {tool.id!r} references table(s) "
                            f"{sorted(missing)!r} that the connector did not "
                            f"materialize. Available tables: {sorted(table_names)!r}."
                        ),
                        detail={
                            "tool_id": tool.id,
                            "missing_tables": sorted(missing),
                            "available_tables": sorted(table_names),
                        },
                    ) from exc
                # A "no such column" error against tables that all exist but
                # are empty is not a real error: an empty table cannot match
                # any WHERE clause / projection, so the correct, non-error
                # result is simply []. (An empty REST envelope like
                # `{"items": []}` materializes a zero-row, zero-column table.)
                if "no such column" in str(exc).lower():
                    referenced = _extract_table_names(sql)
                    existing = [t for t in referenced if t in table_names]
                    if existing and all(_table_is_empty(engine, t) for t in existing):
                        log.info(
                            "tool.empty_source.no_match",
                            tool_id=tool.id,
                            tables=sorted(existing),
                        )
                        return self._capped_result(tool.id, [])
            raise

        return self._capped_result(tool.id, rows)

    def _capped_result(self, tool_id: str, rows: list[dict[str, Any]]) -> QueryResult:
        """Apply the hard row cap, flagging truncation when it bites."""
        cap = max_result_rows()
        if len(rows) > cap:
            log.warning(
                "tool.result.truncated",
                tool_id=tool_id,
                returned=cap,
                total=len(rows),
            )
            return QueryResult(rows=rows[:cap], tool_id=tool_id, truncated=True)
        return QueryResult(rows=rows, tool_id=tool_id)

    # ── materialization ────────────────────────────────────────────────────

    async def _ensure_materialized(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> SQLiteEngine:
        """Make sure every source the tool needs is loaded into the engine.

        Returns the cached engine so the caller can run `query()` directly.
        """
        if self._engine is None:
            self._engine = SQLiteEngine()

        needed = self._sources_needed_for(tool)
        now = time.monotonic()

        for source in needed:
            last = self._materialized_at.get(source.id)
            if last is not None and (now - last) < self._ttl:
                continue
            await self._materialize_source(source, arguments)

        return self._engine

    def _sources_needed_for(self, tool: ToolDefinition) -> list[SourceConfig]:
        """Decide which sources to load for this tool.

        We prefer the tool's declared `source_ids` (authoritative metadata
        written by Studio). If it has none, fall back to materializing
        every configured source — this keeps tools that omit `source_ids`
        working, at the cost of one fetch per source on first call.
        """
        ids = list(tool.source_ids or [])
        if not ids:
            return list(self._sources.values())
        out: list[SourceConfig] = []
        for sid in ids:
            src = self._sources.get(sid)
            if src is None:
                continue
            out.append(src)
        return out

    async def _materialize_source(
        self,
        source: SourceConfig,
        arguments: dict[str, Any],
    ) -> None:
        lock = self._locks.setdefault(source.id, asyncio.Lock())
        async with lock:
            # Recheck inside the lock — another coroutine may have just loaded it.
            last = self._materialized_at.get(source.id)
            if last is not None and (time.monotonic() - last) < self._ttl:
                return

            assert self._engine is not None  # set by _ensure_materialized
            table_name = source.table_name or source.id
            try:
                rows = await self._fetch_source(source, arguments)
            except Exception as exc:
                log.error(
                    "source.materialize.fetch_failed",
                    source_id=source.id,
                    table=table_name,
                    error=str(exc),
                )
                raise

            flat = flatten(rows, table_name=table_name)
            self._engine.load_result(flat)
            self._materialized_at[source.id] = time.monotonic()
            log.info(
                "source.materialized",
                source_id=source.id,
                table=table_name,
                row_count=len(rows),
                child_tables=[t.name for t in flat.related_tables],
            )

    # ── fetchers ───────────────────────────────────────────────────────────

    async def _fetch_source(
        self,
        source: SourceConfig,
        arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if source.type == "rest":
            return await self._fetch_rest(source, arguments)
        if source.type in ("postgres", "mysql"):
            return await self._fetch_db(source)
        if source.type == "file":
            return self._fetch_file(source)
        raise ExecutorError(f"Unsupported source type: {source.type!r}")

    def _fetch_file(self, source: SourceConfig) -> list[dict[str, Any]]:
        from elliot_core.sources.file_reader import read_file

        result = read_file(source)
        return result.rows

    async def _fetch_rest(
        self,
        source: SourceConfig,
        arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        from urllib.parse import urlsplit

        from elliot_core.http import SSRFError, safe_client, validate_url

        url = _interpolate(source.url or "", arguments)
        headers = _build_auth_headers(source.auth, self._secrets) if source.auth else {}
        pagination = source.pagination
        all_rows: list[dict[str, Any]] = []
        page = 1
        offset = 0
        cursor: str | None = None
        next_url: str | None = None
        pages_fetched = 0
        # FIX 3: overall accumulated-row cap so a source with huge pages can't
        # OOM the worker even before max_pages bites.
        row_cap = max_result_rows()

        # SSRF DNS-rebinding defense: validate the initial URL and pin the
        # connection pool to the vetted IP. A cross-host `next` link will fail
        # closed inside `_PinnedTransport` — acceptable, it's safe.
        try:
            initial_ips = validate_url(url)
        except SSRFError as exc:
            raise ExecutorError(f"Refusing to fetch REST source: {exc.message}") from exc
        initial_host = urlsplit(url).hostname or ""
        pinned_hosts = {initial_host: initial_ips[0]} if (initial_host and initial_ips) else None

        async with safe_client(
            timeout=source.timeout_ms / 1000, pinned_hosts=pinned_hosts
        ) as client:
            while True:
                if pages_fetched >= pagination.max_pages:
                    break

                request_url = next_url or url
                try:
                    validate_url(request_url)
                except SSRFError as exc:
                    raise ExecutorError(f"Refusing to fetch REST source: {exc.message}") from exc

                params: dict[str, Any] = {}
                if pagination.strategy == "offset":
                    params["offset"] = offset
                    params["limit"] = pagination.page_size
                elif pagination.strategy == "page":
                    params["page"] = page
                elif pagination.strategy == "cursor" and cursor:
                    params["cursor"] = cursor

                resp = await client.get(request_url, headers=headers, params=params or None)
                resp.raise_for_status()
                pages_fetched += 1

                # Keep the raw response envelope: cursor pagination reads
                # next_cursor from it, and data_path may narrow `data` to a
                # bare list that no longer carries the cursor field.
                envelope = resp.json()
                data = jmespath.search(source.data_path, envelope) if source.data_path else envelope

                # Unwrap a paginated envelope (``{items: [...], total, ...}``)
                # the same way the design-time api_fetcher does. Without this
                # the runtime materializes the wrapper as a single row and
                # the agent's ``FROM "<source>"`` returns nothing.
                rows: list[dict[str, Any]]
                if isinstance(data, list):
                    rows = data
                elif isinstance(data, dict):
                    found: list[dict[str, Any]] | None = None
                    for key in ("data", "items", "results", "records", "rows"):
                        value = data.get(key)
                        if isinstance(value, list):
                            found = value
                            break
                    rows = found if found is not None else [data]
                else:
                    raise ExecutorError(
                        f"REST source {source.id!r} returned unexpected type: {type(data)}"
                    )

                all_rows.extend(rows)

                # FIX 3: stop paginating and truncate once the accumulated
                # row count reaches the cap.
                if len(all_rows) >= row_cap:
                    if len(all_rows) > row_cap:
                        log.warning(
                            "source.fetch.rows_truncated",
                            source_id=source.id,
                            returned=row_cap,
                            accumulated=len(all_rows),
                        )
                        del all_rows[row_cap:]
                    break

                if pagination.strategy == "none" or not rows:
                    break
                if pagination.strategy == "offset":
                    if len(rows) < pagination.page_size:
                        break
                    offset += pagination.page_size
                elif pagination.strategy == "page":
                    if len(rows) < pagination.page_size:
                        break
                    page += 1
                elif pagination.strategy == "cursor":
                    cursor = (
                        envelope.get("next_cursor") if isinstance(envelope, dict) else None
                    ) or (
                        envelope.get(pagination.cursor_field or "cursor")
                        if isinstance(envelope, dict)
                        else None
                    )
                    if not cursor:
                        break
                elif pagination.strategy == "link_header":
                    next_url = _parse_link_next(resp.headers.get("link", ""))
                    if not next_url:
                        break
                else:
                    break

        return all_rows

    async def _fetch_db(self, source: SourceConfig) -> list[dict[str, Any]]:
        """Fetch a whole DB source for the SQLite-snapshot path.

        Routed through elliot_core's SQLAlchemy connector so Postgres and
        MySQL are both supported and Postgres runs in a read-only
        transaction. The push-down path (``_execute_db_pushdown``) avoids
        this whole-table fetch whenever a tool's filters can run server-side.
        """
        from elliot_core.sources.db_connector import query_database

        result = await asyncio.to_thread(query_database, source, self._secrets)
        return result.rows

    def _pushdown_source(self, tool: ToolDefinition) -> SourceConfig | None:
        """Return the DB source a tool's filters can be pushed down to.

        Eligible when there is no injected test engine, the tool has no raw
        SQL but does define filter_groups / return_fields, and it needs
        exactly one source which is a Postgres or MySQL database. Raw-SQL
        tools and multi-source tools keep the SQLite-snapshot path because
        their SQL is authored in the SQLite dialect against snapshot tables.
        """
        if self._injected_engine is not None:
            return None
        if tool.sql:
            return None
        if not (tool.filter_groups or tool.return_fields):
            return None
        needed = self._sources_needed_for(tool)
        if len(needed) != 1:
            return None
        source = needed[0]
        return source if source.type in ("postgres", "mysql") else None

    async def _execute_db_pushdown(
        self,
        tool: ToolDefinition,
        source: SourceConfig,
        arguments: dict[str, Any],
    ) -> QueryResult:
        """Compile the tool to a dialect-correct SELECT and run it on the DB.

        The tool's filter_groups / return_fields / order_by / limit are
        pushed straight to Postgres/MySQL, so the database does the
        filtering and only the matching rows cross the wire — no full-table
        snapshot, and the agent's parameters reach the real query.
        """
        from elliot_core.sources.db_connector import run_select
        from elliot_core.tools.query_builder import build_select_sql

        dialect = source.type  # "postgres" | "mysql"
        from_clause = _db_from_clause(source, dialect)
        sql, params = build_select_sql(tool, arguments, dialect=dialect, from_clause=from_clause)
        result = await asyncio.to_thread(run_select, source, self._secrets, sql, params)
        log.info(
            "tool.db_pushdown",
            tool_id=tool.id,
            source_id=source.id,
            dialect=dialect,
            row_count=len(result.rows),
        )
        return self._capped_result(tool.id, result.rows)


# ── helpers ────────────────────────────────────────────────────────────────────


def _parse_link_next(link_header: str) -> str | None:
    """Return the next URL from an RFC 5988 ``Link: <url>; rel="next"`` header."""
    import re

    m = re.search(r'<([^>]+)>;\s*rel="next"', link_header or "")
    return m.group(1) if m else None


def _extract_table_names(sql: str) -> list[str]:
    """Extract table identifiers after FROM and JOIN keywords.

    Handles both unquoted (FROM items) and double-quoted (FROM "items") forms,
    since build_select_sql always generates double-quoted table names.
    """
    pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+(?:"([a-zA-Z_][a-zA-Z0-9_]*)"|([a-zA-Z_][a-zA-Z0-9_]*))',
        re.IGNORECASE,
    )
    return list(dict.fromkeys(m.group(1) or m.group(2) for m in pattern.finditer(sql)))


def _missing_tables(sql: str, available: list[str]) -> set[str]:
    referenced = set(_extract_table_names(sql))
    return referenced - set(available)


def _table_is_empty(engine: SQLiteEngine, table_name: str) -> bool:
    """Return True if ``table_name`` exists in ``engine`` and holds 0 rows."""
    try:
        return engine.get_table_stats(table_name).get("row_count", 0) == 0
    except Exception:
        # If we can't count it (e.g. it vanished), don't claim it's empty —
        # let the original INVALID_SQL error propagate.
        return False


def _interpolate(template: str, values: dict[str, Any]) -> str:
    """Replace {param} placeholders in a URL template.

    Each value is percent-encoded with ``safe=""`` so an agent-supplied
    argument like ``"../admin"`` cannot escape its path segment or inject
    extra query parameters / URL fragments.
    """
    from urllib.parse import quote

    for key, val in values.items():
        template = template.replace(f"{{{key}}}", quote(str(val), safe=""))
    return template


def _db_from_clause(source: SourceConfig, dialect: str) -> str:
    """Build the FROM expression for a pushed-down DB query.

    Uses the real table name when the source declares one; otherwise wraps
    the source's custom query as a derived table so the tool's WHERE /
    ORDER BY / LIMIT can be layered on top of it.
    """
    from elliot_core.sqlite.query_runner import validate_tool_sql
    from elliot_core.tools.query_builder import quote_ident

    if source.table:
        return quote_ident(source.table, dialect)
    if source.query:
        ok, reason = validate_tool_sql(source.query)
        if not ok:
            raise ExecutorError(f"Source {source.id!r} has an invalid query: {reason}")
        return f"({source.query}) AS _elliot_src"
    raise ExecutorError(f"DB source {source.id!r} has neither 'table' nor 'query' set")


def _resolve_secret(key: str, secrets: dict[str, str]) -> str:
    """Resolve ``auth.secret_key`` to a concrete header value.

    Three paths must work, matching ``elliot_core.sources.api_fetcher``:

    1. ``"{{ env:REVIEWS_TOKEN }}"`` — env-var template. Look it up.
    2. ``"REVIEWS_TOKEN"`` — bare env-var name. Look up via secrets dict
       (with lower-case fallback because the loader lower-cases keys).
    3. The runtime loader applies ``elliot_core.secrets.resolve_secrets``
       at load time, so a template like ``{{ env:X }}`` may already have
       been substituted with the literal secret value. In that case we
       must return the key as-is — it IS the value.

    Mirroring ``api_fetcher`` keeps plugin-time and runtime-time fetches
    behaving identically.
    """
    import os

    if key.startswith("{{ env:") and key.endswith(" }}"):
        env_var = key[len("{{ env:") : -len(" }}")].strip()
        return secrets.get(env_var) or secrets.get(env_var.lower()) or os.environ.get(env_var, "")
    # Case 2: bare env-var name found in the secrets dict (or its lowercase
    # twin). Case 3: anything else is the resolved secret literal — return
    # it unchanged, just like api_fetcher does.
    return secrets.get(key) or secrets.get(key.lower()) or key


def _build_auth_headers(auth: AuthConfig, secrets: dict[str, str]) -> dict[str, str]:
    secret_val = _resolve_secret(auth.secret_key, secrets)
    if auth.type == "api_key":
        header = auth.header_name or "X-Api-Key"
        return {header: secret_val}
    if auth.type in ("bearer", "oauth2"):
        # oauth2: the per-user access token has been injected into `secrets`
        # under auth.secret_key by the credential resolver; carry it as a
        # standard bearer token on every upstream request.
        return {"Authorization": f"Bearer {secret_val}"}
    if auth.type == "basic":
        import base64

        encoded = base64.b64encode(secret_val.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {}
