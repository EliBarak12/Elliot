from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from elliot_core.errors import ElliotError, NotFoundError, SourceFetchError
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
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
    ) -> None:
        self._config = config
        self._source_map = {s.id: s for s in config.sources}
        self._tool_map = {t.id: t for t in config.tools}
        self._secrets = secrets or {}
        self._fetch_source = fetch_source or _default_fetch_source

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
        run generated SELECT with filter_groups / return_fields / order_by.
        """
        fetch_results = await self._fetch_sources(tool.source_ids)

        engine = SQLiteEngine()
        try:
            for source_id, fetch_result in fetch_results.items():
                engine.load_result(flatten(fetch_result.rows, source_id))

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
        if not tool.api_mapping:
            raise ElliotError("MISSING_API_MAPPING", f"WRITE tool '{tool.id}' has no api_mapping")
        source = self._source_map.get(tool.source_ids[0])
        if not source:
            raise ElliotError("SOURCE_NOT_FOUND", f"Source '{tool.source_ids[0]}' not found")

        mapping = tool.api_mapping
        base_url = (source.url or "").rstrip("/")
        path = mapping.path_template or ""
        for name, val in params.items():
            path = path.replace(f"{{{name}}}", str(val))

        url = base_url + path
        query = {k: params[k] for k in mapping.query_params if k in params}
        body = {k: params[k] for k in mapping.body_params if k in params}

        import httpx

        from elliot_core.sources.api_fetcher import _build_auth_headers

        headers = _build_auth_headers(source, self._secrets)

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

    async def _fetch_sources(self, source_ids: list[str]) -> dict[str, FetchResult]:
        async def _one(sid: str) -> tuple[str, FetchResult]:
            source = self._source_map.get(sid)
            if not source:
                raise ElliotError("SOURCE_NOT_FOUND", f"Source '{sid}' not in connector")
            try:
                log.debug("source.fetch.start", source_id=sid)
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


def _coerce_and_validate(tool: ToolDefinition, params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
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
        except (ValueError, TypeError) as exc:
            raise ElliotError("INVALID_PARAM_TYPE", f"Expected integer, got: {val!r}") from exc
    if typ == "number":
        return float(val)
    if typ == "boolean":
        return bool(val)
    return str(val)


def _apply_rename(rows: list[dict[str, Any]], rename: dict[str, str]) -> list[dict[str, Any]]:
    if not rename:
        return rows
    return [{rename.get(k, k): v for k, v in row.items()} for row in rows]
