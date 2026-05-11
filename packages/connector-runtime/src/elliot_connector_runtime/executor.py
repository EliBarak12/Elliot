"""Execute ToolDefinition calls against live data sources."""

from __future__ import annotations

import re
from typing import Any

import httpx
import jmespath

from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.tools.query_builder import build_select_sql
from elliot_core.types import (
    AuthConfig,
    ConnectorConfig,
    QueryResult,
    SourceConfig,
    ToolDefinition,
)


class ExecutorError(Exception):
    pass


class ToolExecutor:
    """
    Executes a ToolDefinition against the connector's live data sources.

    Each call to `execute` fetches fresh data from the relevant source,
    hydrates an ephemeral in-memory SQLiteEngine, and runs the tool's SQL.
    """

    def __init__(
        self,
        config: ConnectorConfig,
        secrets: dict[str, str],
        engine: SQLiteEngine | None = None,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._sources: dict[str, SourceConfig] = {s.id: s for s in config.sources}
        self._engine = engine  # injected engine for testing / pre-loaded data

    async def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> QueryResult:
        # Determine SQL: prefer explicit sql, fall back to build_select_sql for filter_groups tools
        if tool.sql:
            sql: str = tool.sql
            params: dict[str, Any] = {p.name: arguments.get(p.name) for p in tool.parameters}
        elif tool.filter_groups or tool.return_fields:
            sql, params = build_select_sql(tool, arguments)
        else:
            raise ExecutorError(f"Tool '{tool.id}' has no sql or filter_groups defined")

        # Use injected engine or fetch from live sources into a fresh engine
        if self._engine is not None:
            rows = self._engine.query(sql, params)
            return QueryResult(rows=rows, tool_id=tool.id)

        engine = SQLiteEngine()
        any_empty = False

        for source_id in _extract_table_names(sql):
            source = self._sources.get(source_id)
            if source is None:
                continue
            fetched = await self._fetch_source(source, arguments)
            if not fetched:
                any_empty = True
                continue
            engine.ingest(source_id, fetched)

        if any_empty:
            return QueryResult(rows=[], tool_id=tool.id)

        rows = engine.query(sql, params)
        return QueryResult(rows=rows, tool_id=tool.id)

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
        url = _interpolate(source.url or "", arguments)
        headers = _build_auth_headers(source.auth, self._secrets) if source.auth else {}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()

        data = resp.json()

        if source.data_path:
            data = jmespath.search(source.data_path, data)

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise ExecutorError(f"REST source {source.id!r} returned unexpected type: {type(data)}")

    async def _fetch_db(self, source: SourceConfig) -> list[dict[str, Any]]:
        import asyncio
        import functools

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(self._query_postgres, source))

    def _query_postgres(self, source: SourceConfig) -> list[dict[str, Any]]:
        import psycopg2
        import psycopg2.extras

        dsn = self._resolve_dsn(source)
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(source.query or f"SELECT * FROM {source.table}")
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def _resolve_dsn(self, source: SourceConfig) -> str:
        if source.auth and source.auth.secret_key:
            return self._secrets.get(source.auth.secret_key, "")
        return source.url or ""


# ── helpers ────────────────────────────────────────────────────────────────────


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


def _interpolate(template: str, values: dict[str, Any]) -> str:
    """Replace {param} placeholders in a URL template."""
    for key, val in values.items():
        template = template.replace(f"{{{key}}}", str(val))
    return template


def _build_auth_headers(auth: AuthConfig, secrets: dict[str, str]) -> dict[str, str]:
    secret_val = secrets.get(auth.secret_key, "")
    if auth.type == "api_key":
        header = auth.header_name or "X-Api-Key"
        return {header: secret_val}
    if auth.type == "bearer":
        return {"Authorization": f"Bearer {secret_val}"}
    if auth.type == "basic":
        import base64

        encoded = base64.b64encode(secret_val.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {}
