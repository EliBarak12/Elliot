from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from elliot_core.errors import ElliotError, NotFoundError, SourceFetchError
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
from elliot_core.tools.param_validation import coerce_value as _coerce  # noqa: F401  (re-exported)
from elliot_core.tools.param_validation import validate_call_params
from elliot_core.tools.query_builder import build_select_sql
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import FetchResult, SourceConfig
from elliot_core.types.tool import ToolDefinition, ToolResult

log = structlog.get_logger(__name__)


async def _default_fetch_source(source: SourceConfig, secrets: dict[str, str]) -> FetchResult:
    if source.type == "rest":
        from elliot_core.sources.api_fetcher import fetch_endpoint

        return await fetch_endpoint(source, secrets)
    if source.type == "file":
        from elliot_core.sources.file_reader import read_file

        return await asyncio.to_thread(read_file, source)
    if source.type in ("postgres", "mysql"):
        from elliot_core.sources.db_connector import query_database

        return await asyncio.to_thread(query_database, source, secrets)
    raise ElliotError("INVALID_TOOL", f"Unknown source type: {source.type}")


class ToolExecutor:
    def __init__(
        self,
        config: ConnectorConfig,
        secrets: dict[str, str] | None = None,
        fetch_source: Any = None,
        managed_store: Any = None,
    ) -> None:
        self._config = config
        self._source_map = {s.id: s for s in config.sources}
        self._tool_map = {t.id: t for t in config.tools}
        self._secrets = secrets or {}
        self._fetch_source = fetch_source or _default_fetch_source
        # Persistent store for managed ("elliot") sources; lazily opened at
        # ELLIOT_MANAGED_DB when the connector declares one.
        self._managed_store = managed_store

    def _managed(self) -> Any:
        if self._managed_store is None:
            from elliot_core.sqlite.managed_store import ManagedStore, managed_db_path

            self._managed_store = ManagedStore(managed_db_path())
        return self._managed_store

    async def execute(self, tool_id: str, params: dict[str, Any]) -> ToolResult:
        tool = self._tool_map.get(tool_id)
        if not tool:
            raise NotFoundError(f"Tool '{tool_id}' not found")

        log.info("tool.call.start", tool_id=tool_id, category=tool.category)
        t0 = time.monotonic()
        bound = _coerce_and_validate(tool, params)

        result = (
            await self._execute_read(tool, bound)
            if tool.category == "READ"
            else await self._execute_write(tool, bound)
        )

        log.info(
            "tool.call.complete",
            tool_id=tool_id,
            rows=len(result.rows),
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
        return result

    async def _execute_read(self, tool: ToolDefinition, params: dict[str, Any]) -> ToolResult:
        # ── Passthrough mode: agent params forwarded as API query params ──────────
        if tool.rest_query_params:
            return await self._execute_read_passthrough(tool, params)

        # ── Full-fetch mode: fetch all rows → SQLite → generated SELECT ────────
        return await self._execute_read_full(tool, params)

    async def _execute_read_passthrough(
        self, tool: ToolDefinition, params: dict[str, Any]
    ) -> ToolResult:
        """
        Passthrough mode: forward rest_query_params values directly to the API
        as query string parameters. Returns the API response without full pagination.
        Optionally applies filter_groups as a post-fetch SQL filter.
        """
        if not tool.source_ids:
            raise ElliotError("INVALID_TOOL", f"Tool '{tool.id}' has no source_ids")
        source = self._source_map.get(tool.source_ids[0])
        if not source:
            raise ElliotError("SOURCE_NOT_FOUND", f"Source '{tool.source_ids[0]}' not found")
        if source.type != "rest":
            raise ElliotError(
                "INVALID_TOOL",
                f"Tool '{tool.id}' uses rest_query_params but source '{source.id}' "
                f"is type '{source.type}', not 'rest'",
            )

        api_params = {k: params[k] for k in tool.rest_query_params if k in params}
        log.debug("tool.passthrough", tool_id=tool.id, api_params=list(api_params))

        from elliot_core.sources.passthrough_fetcher import fetch_passthrough

        fetch_result = await fetch_passthrough(source, self._secrets, api_params)

        rows = fetch_result.rows

        # Optional: apply filter_groups / return_fields as SQL post-filter
        if tool.filter_groups or tool.return_fields or tool.having or tool.order_by:
            engine = SQLiteEngine()
            try:
                engine.load_result(flatten(rows, source.id))
                sql, sql_params = build_select_sql(tool, params)
                rows = engine.query(sql, sql_params)
            finally:
                engine.close()

        truncated = len(rows) > tool.response_shape.max_rows
        rows = rows[: tool.response_shape.max_rows]
        rows = _apply_rename(rows, tool.response_shape.rename)

        return ToolResult(
            rows=rows,
            meta={
                "fetch_mode": "passthrough",
                "row_count": len(rows),
                "truncated": truncated,
                "api_params_sent": list(api_params.keys()),
            },
        )

    async def _execute_read_full(self, tool: ToolDefinition, params: dict[str, Any]) -> ToolResult:
        """
        Full-fetch mode: retrieve all pages from source, load into SQLite,
        then run the tool's SQL (preferring tool.sql when set, otherwise the
        SELECT generated from filter_groups / return_fields / order_by).
        """
        fetch_results = await self._fetch_sources(tool.source_ids)

        engine = SQLiteEngine()
        try:
            for source_id, fetch_result in fetch_results.items():
                # Prefer the discovered table_name (matches user SQL like FROM customers)
                # falling back to source.id (the built-connector case where id == name).
                source = self._source_map.get(source_id)
                table_name = source.table_name if source and source.table_name else source_id
                if source is not None and source.type == "elliot":
                    # Managed rows keep their store-minted ``_id`` (the handle
                    # mutations target); the flattener would renumber it.
                    from elliot_core.sqlite.managed_store import managed_flat_table

                    engine.load_result(managed_flat_table(source, fetch_result.rows))
                else:
                    engine.load_result(flatten(fetch_result.rows, table_name))

            if tool.sql:
                # Defence in depth: a stored tool.sql must be a read-only
                # SELECT before it runs against the in-memory mirror, even if a
                # caller bypassed the create/update validation path.
                from elliot_core.sqlite.query_runner import validate_tool_sql

                valid, reason = validate_tool_sql(tool.sql)
                if not valid:
                    raise ElliotError("INVALID_SQL", reason)
                sql = tool.sql
                sql_params = {p.name: params.get(p.name) for p in tool.parameters}
            else:
                sql, sql_params = build_select_sql(tool, params)
            try:
                rows = engine.query(sql, sql_params)
            except Exception as exc:
                log.error("tool.sql.failed", tool_id=tool.id, error=str(exc))
                raise ElliotError("SQL_EXECUTION_FAILED", str(exc)) from exc
        finally:
            engine.close()

        truncated = len(rows) > tool.response_shape.max_rows
        rows = rows[: tool.response_shape.max_rows]
        rows = _apply_rename(rows, tool.response_shape.rename)

        return ToolResult(
            rows=rows,
            meta={
                "fetch_mode": "full",
                "row_count": len(rows),
                "truncated": truncated,
                "sources_fetched": list(fetch_results.keys()),
            },
        )

    async def _execute_write(self, tool: ToolDefinition, params: dict[str, Any]) -> ToolResult:
        if tool.data_mapping is not None:
            return await self._execute_data_write(tool, params)
        if not tool.api_mapping:
            raise ElliotError("MISSING_API_MAPPING", f"WRITE tool '{tool.id}' has no api_mapping")
        if not tool.source_ids:
            raise ElliotError("INVALID_TOOL", f"{tool.category} tool '{tool.id}' has no source_ids")
        source = self._source_map.get(tool.source_ids[0])
        if not source:
            raise ElliotError("SOURCE_NOT_FOUND", f"Source '{tool.source_ids[0]}' not found")

        from urllib.parse import quote

        mapping = tool.api_mapping
        base_url = (source.url or "").rstrip("/")
        path = mapping.path_template or ""
        # Audit H4: previously `.replace("{key}", str(val))` substituted
        # ANY param name and never URL-encoded the value, so an attacker-
        # supplied id like "../admin?force=1" would mutate URL semantics.
        # Only substitute declared placeholders, and URL-encode each value
        # (safe="" so `/`, `?`, `#`, `..` are all percent-encoded).
        declared = {p.name for p in tool.parameters}
        for name, val in params.items():
            if name not in declared:
                continue
            path = path.replace(f"{{{name}}}", quote(str(val), safe=""))

        url = base_url + path
        query = {k: params[k] for k in mapping.query_params if k in params}
        # The source's static `body` is the base (carries fixed fields the
        # endpoint always wants, e.g. {"store": "331"}); the tool's mapped
        # body_params override it per call.
        body = {**(source.body or {}), **{k: params[k] for k in mapping.body_params if k in params}}

        import httpx

        from elliot_core.sources.api_fetcher import _request_headers

        # Full header set: the source's custom headers (extra credentials like
        # `ecomtoken` / `cookie`, content framing) with the auth header on top.
        headers = _request_headers(source, self._secrets)

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
            rows: list[dict[str, Any]] = data if isinstance(data, list) else [data]
        except httpx.HTTPStatusError as exc:
            log.error("tool.write.http_error", tool_id=tool.id, status=exc.response.status_code)
            raise ElliotError(
                "API_REQUEST_FAILED",
                f"API returned {exc.response.status_code}",
            ) from exc
        except ElliotError:
            raise
        except Exception as exc:
            log.error("tool.write.failed", tool_id=tool.id, error=str(exc))
            raise ElliotError("API_REQUEST_FAILED", str(exc)) from exc

        return ToolResult(
            rows=rows, meta={"fetch_mode": "write", "row_count": len(rows), "url": url}
        )

    async def _execute_data_write(self, tool: ToolDefinition, params: dict[str, Any]) -> ToolResult:
        """WRITE against a managed ("elliot") source's persistent store.

        Inserts stamp the current caller as the row's owner; updates and
        deletes only reach rows the caller owns or holds a write grant on —
        the store enforces this, not the tool.
        """
        from elliot_core.user_identity import managed_owner_id, managed_write_owner_ids

        mapping = tool.data_mapping
        assert mapping is not None  # caller-checked
        if not tool.source_ids:
            raise ElliotError("INVALID_TOOL", f"WRITE tool '{tool.id}' has no source_ids")
        source = self._source_map.get(tool.source_ids[0])
        if not source:
            raise ElliotError("SOURCE_NOT_FOUND", f"Source '{tool.source_ids[0]}' not found")
        if source.type != "elliot":
            raise ElliotError(
                "INVALID_TOOL",
                f"Tool '{tool.id}' has a data_mapping but source '{source.id}' is type "
                f"'{source.type}', not a managed 'elliot' source",
            )

        values = {
            column: params[param]
            for column, param in mapping.column_params.items()
            if params.get(param) is not None
        }
        store = self._managed()

        if mapping.operation == "insert":
            row = await asyncio.to_thread(store.insert_row, source, values, managed_owner_id())
        elif not mapping.key_param:
            raise ElliotError(
                "INVALID_TOOL",
                f"Tool '{tool.id}' performs a managed {mapping.operation} but declares no "
                "key_param carrying the target row's _id",
            )
        else:
            row_id = params.get(mapping.key_param)
            if row_id in (None, ""):
                raise ElliotError(
                    "VALIDATION_REQUIRED",
                    f"Parameter '{mapping.key_param}' (the target row's _id) is required.",
                )
            allowed = managed_write_owner_ids()
            if mapping.operation == "update":
                row = await asyncio.to_thread(
                    store.update_row, source, str(row_id), values, allowed
                )
            else:
                row = await asyncio.to_thread(store.delete_row, source, str(row_id), allowed)

        return ToolResult(
            rows=[row],
            meta={"fetch_mode": "data_write", "operation": mapping.operation, "row_count": 1},
        )

    async def _fetch_managed(self, source: SourceConfig) -> FetchResult:
        """Read a managed source's rows, scoped to the current caller."""
        from datetime import UTC, datetime

        from elliot_core.user_identity import managed_read_owner_ids

        rows = await asyncio.to_thread(self._managed().read_rows, source, managed_read_owner_ids())
        return FetchResult(rows=rows, fetched_at=datetime.now(UTC).isoformat())

    async def _fetch_sources(self, source_ids: list[str]) -> dict[str, FetchResult]:
        async def _one(sid: str) -> tuple[str, FetchResult]:
            source = self._source_map.get(sid)
            if not source:
                raise ElliotError("SOURCE_NOT_FOUND", f"Source '{sid}' not in connector")
            try:
                log.debug("source.fetch.start", source_id=sid)
                if source.type == "elliot":
                    result = await self._fetch_managed(source)
                else:
                    result = await self._fetch_source(source, self._secrets)
                log.debug("source.fetch.complete", source_id=sid, rows=len(result.rows))
                return sid, result
            except ElliotError:
                raise
            except Exception as exc:
                log.error("source.fetch.failed", source_id=sid, error=str(exc))
                raise SourceFetchError(f"Failed to fetch source '{sid}': {exc}") from exc

        pairs = await asyncio.gather(*[_one(sid) for sid in source_ids])
        return dict(pairs)


# Parameter validation/coercion now lives in elliot_core.tools.param_validation
# so the design-time executor, the plugin preview path, and the published
# runtime all bind inputs identically (audit H5/H6). These thin aliases keep
# the long-standing internal names stable for callers and tests.
def _coerce_and_validate(tool: ToolDefinition, params: dict[str, Any]) -> dict[str, Any]:
    return validate_call_params(tool, params, declared_only=True)


def _apply_rename(rows: list[dict[str, Any]], rename: dict[str, str]) -> list[dict[str, Any]]:
    if not rename:
        return rows
    return [{rename.get(k, k): v for k, v in row.items()} for row in rows]
