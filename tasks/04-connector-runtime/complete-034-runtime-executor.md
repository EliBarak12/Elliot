# Task 034 — Runtime: Tool Executor

## Goal
Implement `executor.py` inside `packages/connector-runtime/src/elliot_connector_runtime/` to execute `ToolDefinition` calls against live data sources (REST APIs and databases) and return structured results.

## File to create

### `src/elliot_connector_runtime/executor.py`

```python
from __future__ import annotations

import re
import sqlite3
from typing import Any

import httpx
import jmespath

from elliot_core.types import (
    AuthConfig,
    ConnectorConfig,
    QueryResult,
    SourceConfig,
    ToolDefinition,
)
from elliot_core.sqlite_engine import SQLiteEngine


class ExecutorError(Exception):
    pass


class ToolExecutor:
    """
    Executes a ToolDefinition against the connector's live data sources.

    Each call to `execute` fetches fresh data from the relevant source,
    hydrates the in-memory SQLiteEngine, and runs the tool's SQL query.
    """

    def __init__(self, config: ConnectorConfig, secrets: dict[str, str]) -> None:
        self._config = config
        self._secrets = secrets
        self._sources: dict[str, SourceConfig] = {s.id: s for s in config.sources}

    async def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> QueryResult:
        engine = SQLiteEngine()

        # Determine which sources this tool needs
        source_ids = _extract_table_names(tool.sql)

        for source_id in source_ids:
            source = self._sources.get(source_id)
            if source is None:
                continue
            rows = await self._fetch_source(source, arguments)
            engine.ingest(source_id, rows)

        # Bind :param style parameters
        params = {p.name: arguments.get(p.name) for p in tool.parameters}
        rows = engine.query(tool.sql, params)
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
        raise ExecutorError(f"Unsupported source type: {source.type!r}")

    async def _fetch_rest(
        self,
        source: SourceConfig,
        arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        url = _interpolate(source.url, arguments)
        headers = _build_auth_headers(source.auth, self._secrets) if source.auth else {}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()

        data = resp.json()

        # If a data_path is set, extract the list using jmespath
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
        return source.url


# ── helpers ────────────────────────────────────────────────────────────────────────────


def _extract_table_names(sql: str) -> list[str]:
    """
    Naively extract table identifiers after FROM and JOIN keywords.
    Good enough for the tool SQL patterns used in connectors.
    """
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        re.IGNORECASE,
    )
    return list(dict.fromkeys(m.group(1) for m in pattern.finditer(sql)))


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
```

## Notes on design

- **Ephemeral `SQLiteEngine` per call**: Each `execute` call creates a fresh in-memory SQLite. This avoids stale data between calls.
- **`_extract_table_names`**: Simple regex; good enough because connectors write SQL against named sources (table names equal source IDs).
- **URL interpolation**: `{param}` placeholders in REST `url` field are replaced with argument values before fetching.
- **DB fetching**: psycopg2 is synchronous, so it runs in `asyncio.get_running_loop().run_in_executor` to avoid blocking the event loop.
- **`data_path`** on `SourceConfig`: optional jmespath expression to extract the list from the REST response (e.g., `"items"` or `"data.results"`).

## Add `data_path` to `SourceConfig` (task 005 amendment)

Add this field to `SourceConfig` in `elliot_core/types.py`:

```python
class SourceConfig(BaseModel):
    id: str
    name: str
    type: Literal["rest", "postgres", "mysql", "file"]
    url: str
    table: Optional[str] = None
    query: Optional[str] = None
    data_path: Optional[str] = None          # ← add this
    auth: Optional[AuthConfig] = None
```

## Tests (`packages/connector-runtime/tests/test_executor.py`)

```python
import pytest
import respx
import httpx

from elliot_core.types import ConnectorConfig, SourceConfig, ToolDefinition, ParameterDefinition

from elliot_connector_runtime.executor import ToolExecutor, _extract_table_names, _interpolate


CONNECTOR = ConnectorConfig(
    name="Pets",
    slug="pets",
    version="1.0.0",
    sources=[
        SourceConfig(
            id="animals",
            name="Animals API",
            type="rest",
            url="https://api.example.com/animals",
            data_path="items",
        )
    ],
    tools=[
        ToolDefinition(
            id="list_animals",
            name="List animals",
            description="List all animals",
            category="READ",
            sql="SELECT * FROM animals WHERE species = :species",
            parameters=[
                ParameterDefinition(name="species", type="string", required=True, description="")
            ],
        )
    ],
    skills=[],
)


def test_extract_table_names():
    sql = "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
    assert _extract_table_names(sql) == ["orders", "customers"]


def test_interpolate():
    url = "https://api.example.com/users/{user_id}/posts"
    result = _interpolate(url, {"user_id": "42"})
    assert result == "https://api.example.com/users/42/posts"


@pytest.mark.asyncio
@respx.mock
async def test_executor_rest_source():
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "species": "cat", "name": "Whiskers"}]},
        )
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "cat"})

    assert len(result.rows) == 1
    assert result.rows[0]["name"] == "Whiskers"
    assert result.tool_id == "list_animals"


@pytest.mark.asyncio
@respx.mock
async def test_executor_empty_result():
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "dragon"})
    assert result.rows == []
```
