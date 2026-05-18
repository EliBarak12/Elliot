"""Tests for ToolExecutor."""

from __future__ import annotations

import httpx
import pytest
import respx

from elliot_connector_runtime.executor import (
    ExecutorError,
    ToolExecutor,
    _extract_table_names,
    _interpolate,
)
from elliot_core.types import (
    ConnectorConfig,
    ParameterDefinition,
    ReturnField,
    SourceConfig,
    ToolDefinition,
)

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


def test_extract_table_names() -> None:
    sql = "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
    assert _extract_table_names(sql) == ["orders", "customers"]


def test_extract_table_names_deduplicates() -> None:
    sql = "SELECT * FROM items JOIN items AS i2 ON items.id = i2.parent_id"
    assert _extract_table_names(sql) == ["items"]


def test_extract_table_names_quoted() -> None:
    """build_select_sql generates double-quoted table names; these must be extracted."""
    sql = 'SELECT "id", "name" FROM "customers" ORDER BY "name" DESC LIMIT 50'
    assert _extract_table_names(sql) == ["customers"]


def test_extract_table_names_quoted_join() -> None:
    sql = 'SELECT * FROM "orders" JOIN "customers" ON "orders"."cid" = "customers"."id"'
    assert _extract_table_names(sql) == ["orders", "customers"]


def test_interpolate() -> None:
    url = "https://api.example.com/users/{user_id}/posts"
    result = _interpolate(url, {"user_id": "42"})
    assert result == "https://api.example.com/users/42/posts"


def test_interpolate_no_placeholders() -> None:
    url = "https://api.example.com/users"
    assert _interpolate(url, {"user_id": "42"}) == url


@respx.mock
async def test_executor_rest_source() -> None:
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


@respx.mock
async def test_executor_empty_result() -> None:
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "dragon"})
    assert result.rows == []


@respx.mock
async def test_executor_rest_source_row_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A REST source with huge pages is truncated at ELLIOT_MAX_RESULT_ROWS so
    pagination cannot OOM the worker even before max_pages bites."""
    monkeypatch.setenv("ELLIOT_MAX_RESULT_ROWS", "3")
    # Page returns more rows than the cap; data_path "items" unwraps them.
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": i, "species": "cat"} for i in range(20)]},
        )
    )
    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "cat"})
    # Materialized rows are capped at 3, so the WHERE species='cat' query
    # cannot return more than 3.
    assert len(result.rows) <= 3


async def test_executor_no_sql_no_filter_groups_raises() -> None:
    """A tool with no sql AND empty filter_groups AND empty return_fields raises ExecutorError.

    The elif uses truthiness so that default empty lists fall through to the else clause.
    """
    connector = ConnectorConfig(
        name="Empty",
        slug="empty",
        version="1.0.0",
        sources=[SourceConfig(id="somewhere", name="Somewhere", type="rest", url="http://x.com")],
        tools=[
            ToolDefinition(
                id="no_sql_tool",
                name="No SQL",
                description="Tool without SQL",
                category="READ",
                sql=None,
                source_ids=["somewhere"],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    tool = connector.tools[0]
    with pytest.raises(ExecutorError, match="no sql or filter_groups defined"):
        await executor.execute(tool, {})


async def test_executor_file_source(tmp_path: pytest.TempPathFactory) -> None:
    """File sources are loaded directly without HTTP."""
    import json

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1, "name": "widget"}, {"id": 2, "name": "gadget"}]))

    connector = ConnectorConfig(
        name="FileTest",
        slug="file-test",
        version="1.0.0",
        sources=[
            SourceConfig(id="items", name="Items", type="file", path=str(data_file), format="json")
        ],
        tools=[
            ToolDefinition(
                id="list_items",
                name="List items",
                description="List all items",
                category="READ",
                sql="SELECT * FROM items",
                parameters=[],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})

    assert len(result.rows) == 2
    assert result.rows[0]["name"] == "widget"


async def test_executor_file_source_with_filter(tmp_path: pytest.TempPathFactory) -> None:
    """File source with parameterized SQL filters correctly."""
    import json

    data_file = tmp_path / "products.json"
    data_file.write_text(
        json.dumps(
            [
                {"id": 1, "category": "electronics", "price": 99},
                {"id": 2, "category": "clothing", "price": 49},
                {"id": 3, "category": "electronics", "price": 199},
            ]
        )
    )

    connector = ConnectorConfig(
        name="Products",
        slug="products",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="products", name="Products", type="file", path=str(data_file), format="json"
            )
        ],
        tools=[
            ToolDefinition(
                id="list_by_category",
                name="List by category",
                description="Filter products by category",
                category="READ",
                sql="SELECT * FROM products WHERE category = :category",
                parameters=[
                    ParameterDefinition(
                        name="category", type="string", required=True, description=""
                    )
                ],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"category": "electronics"})

    assert len(result.rows) == 2
    assert all(r["category"] == "electronics" for r in result.rows)


async def test_executor_unsupported_source_raises() -> None:
    """Unknown source types raise ExecutorError."""
    connector = ConnectorConfig(
        name="Bad",
        slug="bad",
        version="1.0.0",
        sources=[SourceConfig(id="x", name="X", type="rest", url="http://x.com")],
        tools=[
            ToolDefinition(
                id="t",
                name="T",
                description="T",
                category="READ",
                sql="SELECT * FROM x",
                parameters=[],
            )
        ],
        skills=[],
    )
    # Patch the source type to something unsupported after construction
    executor = ToolExecutor(connector, secrets={})
    executor._sources["x"].type = "graphql"  # type: ignore[assignment]
    with pytest.raises(ExecutorError, match="Unsupported source type"):
        await executor.execute(connector.tools[0], {})


@respx.mock
async def test_executor_unknown_source_skipped() -> None:
    """Table names in SQL that don't match any source are silently skipped."""
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "species": "dog", "name": "Rex"}]},
        )
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "dog"})
    assert result.rows[0]["name"] == "Rex"


async def test_executor_flattens_nested_json_source(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Regression: connector tools authored against flattener-shaped names
    (e.g. `insights` plus child `insights_facts`) used to fail with
    `no such table` because the runtime only ingested a single flat table
    named after `source.id`. The executor must run the flattener so both
    primary and child tables exist with their authored names.
    """
    import json

    data_file = tmp_path / "insights.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": "a",
                    "label": "north",
                    "facts": [
                        {"k": "visits", "v": 10},
                        {"k": "signups", "v": 2},
                    ],
                },
                {
                    "id": "b",
                    "label": "south",
                    "facts": [{"k": "visits", "v": 5}],
                },
            ]
        )
    )

    connector = ConnectorConfig(
        name="Insights",
        slug="insights",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="src-uuid-1234",
                name="insights",
                type="file",
                path=str(data_file),
                format="json",
                # Studio sets table_name during discovery — that's what
                # tool SQL is authored against.
                table_name="insights",
            )
        ],
        tools=[
            ToolDefinition(
                id="overview",
                name="Overview",
                description="Top-level rows",
                category="READ",
                sql='SELECT * FROM "insights"',
                source_ids=["src-uuid-1234"],
            ),
            ToolDefinition(
                id="facts",
                name="Facts",
                description="Nested facts via child table",
                category="READ",
                sql='SELECT * FROM "insights_facts"',
                source_ids=["src-uuid-1234"],
            ),
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})

    overview = await executor.execute(connector.tools[0], {})
    assert {r["label"] for r in overview.rows} == {"north", "south"}

    facts = await executor.execute(connector.tools[1], {})
    assert len(facts.rows) == 3
    assert {r["k"] for r in facts.rows} == {"visits", "signups"}


async def test_executor_missing_table_raises_actionable_error(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """SQL referencing a table the connector didn't materialize gets a
    typed error naming the missing tables — not a raw `no such table`."""
    import json

    from elliot_core.errors import ElliotError

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1}]))

    connector = ConnectorConfig(
        name="Bad",
        slug="bad",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(data_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="broken",
                name="Broken",
                description="references a table that was never materialized",
                category="READ",
                sql='SELECT * FROM "nonexistent_table"',
                source_ids=["items"],
            )
        ],
        skills=[],
    )

    executor = ToolExecutor(connector, secrets={})
    with pytest.raises(ElliotError) as exc:
        await executor.execute(connector.tools[0], {})
    assert exc.value.code == "TABLE_NOT_FOUND"
    assert "nonexistent_table" in exc.value.message
    assert exc.value.detail is not None
    assert "nonexistent_table" in exc.value.detail["missing_tables"]


async def test_executor_materialization_is_cached(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Second call against the same source must not re-read the file
    (a 4.7 MB file shouldn't be flattened on every tool call)."""
    import json

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1, "name": "first"}]))

    connector = ConnectorConfig(
        name="Items",
        slug="items",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(data_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="list",
                name="List",
                description="List items",
                category="READ",
                sql='SELECT * FROM "items"',
                source_ids=["items"],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})

    first = await executor.execute(connector.tools[0], {})
    assert first.rows[0]["name"] == "first"

    # Mutate the file. If the executor refetches every call, we'd see "second".
    data_file.write_text(json.dumps([{"id": 1, "name": "second"}]))

    second = await executor.execute(connector.tools[0], {})
    assert second.rows[0]["name"] == "first"


async def test_executor_materialization_ttl_refresh(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """When TTL is 0 every call re-materializes — used to verify the TTL
    branch in the cache, and to give operators a way to opt out."""
    import json

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1, "name": "v1"}]))

    connector = ConnectorConfig(
        name="Items",
        slug="items",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(data_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="list",
                name="List",
                description="List items",
                category="READ",
                sql='SELECT * FROM "items"',
                source_ids=["items"],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={}, materialization_ttl_seconds=0)

    first = await executor.execute(connector.tools[0], {})
    assert first.rows[0]["name"] == "v1"

    data_file.write_text(json.dumps([{"id": 1, "name": "v2"}]))

    second = await executor.execute(connector.tools[0], {})
    assert second.rows[0]["name"] == "v2"


async def test_executor_falls_back_to_all_sources_when_source_ids_empty(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Tools that don't declare source_ids still materialize every source —
    keeps older connector definitions working."""
    import json

    items_file = tmp_path / "items.json"
    items_file.write_text(json.dumps([{"id": 1, "name": "widget"}]))

    connector = ConnectorConfig(
        name="Items",
        slug="items",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(items_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="list",
                name="List items",
                description="No source_ids — fall back to all sources",
                category="READ",
                sql='SELECT * FROM "items"',
                # NOTE: no source_ids
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})
    assert result.rows[0]["name"] == "widget"


# ── DB filter push-down ────────────────────────────────────────────────────


def test_db_from_clause_table() -> None:
    """A DB source with a table name yields a dialect-quoted FROM."""
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(id="db", name="DB", type="postgres", table="orders")
    assert _db_from_clause(src, "postgres") == '"orders"'
    assert _db_from_clause(src, "mysql") == "`orders`"


def test_db_from_clause_wraps_custom_query() -> None:
    """A DB source with a custom query is wrapped as a derived table so the
    tool's WHERE / LIMIT can layer on top of it."""
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(
        id="db", name="DB", type="postgres", query="SELECT * FROM orders WHERE active"
    )
    assert _db_from_clause(src, "postgres") == "(SELECT * FROM orders WHERE active) AS _elliot_src"


def test_db_from_clause_rejects_non_select_query() -> None:
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(id="db", name="DB", type="postgres", query="DROP TABLE orders")
    with pytest.raises(ExecutorError, match="invalid query"):
        _db_from_clause(src, "postgres")


def test_db_from_clause_requires_table_or_query() -> None:
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(id="db", name="DB", type="postgres", url="postgresql://x/y")
    with pytest.raises(ExecutorError, match="neither 'table' nor 'query'"):
        _db_from_clause(src, "postgres")


async def test_executor_db_pushdown_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filter_groups tool on a single Postgres source pushes its WHERE
    straight to the database instead of snapshotting the whole table."""
    from elliot_core.sources import db_connector
    from elliot_core.types.source import FetchResult
    from elliot_core.types.tool import FilterCondition, FilterGroup

    captured: dict[str, str] = {}

    def fake_run_select(
        config: SourceConfig,
        secrets: dict[str, str],
        sql: str,
        params: dict[str, object] | None,
    ) -> FetchResult:
        captured["sql"] = sql
        captured["params"] = str(params)
        captured["source_id"] = config.id
        return FetchResult(rows=[{"id": 1, "status": "open"}], fetched_at="2026-01-01T00:00:00Z")

    monkeypatch.setattr(db_connector, "run_select", fake_run_select)

    connector = ConnectorConfig(
        name="Orders",
        slug="orders",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="db",
                name="DB",
                type="postgres",
                url="postgresql://localhost/test",
                table="orders",
            )
        ],
        tools=[
            ToolDefinition(
                id="orders_by_status",
                name="Orders by status",
                description="List orders filtered by status",
                category="READ",
                source_ids=["db"],
                filter_groups=[
                    FilterGroup(
                        conditions=[
                            FilterCondition(field="status", operator="=", parameter_name="status")
                        ]
                    )
                ],
                parameters=[
                    ParameterDefinition(name="status", type="string", required=True, description="")
                ],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"status": "open"})

    assert result.rows == [{"id": 1, "status": "open"}]
    assert captured["source_id"] == "db"
    assert 'FROM "orders"' in captured["sql"]
    assert "WHERE" in captured["sql"]
    # The agent's parameter value reaches the bound params of the real query.
    assert "open" in captured["params"]


async def test_executor_db_pushdown_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    """MySQL push-down quotes identifiers with backticks."""
    from elliot_core.sources import db_connector
    from elliot_core.types.source import FetchResult

    captured: dict[str, str] = {}

    def fake_run_select(
        config: SourceConfig,
        secrets: dict[str, str],
        sql: str,
        params: dict[str, object] | None,
    ) -> FetchResult:
        captured["sql"] = sql
        return FetchResult(rows=[{"order_id": 9}], fetched_at="x")

    monkeypatch.setattr(db_connector, "run_select", fake_run_select)

    connector = ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="db",
                name="DB",
                type="mysql",
                url="mysql+pymysql://root:pass@localhost/test",
                table="orders",
            )
        ],
        tools=[
            ToolDefinition(
                id="recent_orders",
                name="Recent orders",
                description="List recent order ids",
                category="READ",
                source_ids=["db"],
                return_fields=[ReturnField(field="order_id")],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})

    assert result.rows == [{"order_id": 9}]
    assert "FROM `orders`" in captured["sql"]
    assert "`order_id`" in captured["sql"]


async def test_executor_db_pushdown_skipped_for_raw_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB tool with raw SQL keeps the SQLite-snapshot path — its SQL is
    authored in the SQLite dialect, so it cannot be pushed to Postgres."""
    from elliot_core.sources import db_connector
    from elliot_core.types.source import FetchResult

    calls: list[str] = []

    def fake_query_database(config: SourceConfig, secrets: dict[str, str]) -> FetchResult:
        calls.append("query_database")
        return FetchResult(rows=[{"id": 1, "status": "open"}], fetched_at="x")

    def fake_run_select(*args: object, **kwargs: object) -> FetchResult:
        calls.append("run_select")
        raise AssertionError("push-down must not run for a raw-SQL tool")

    monkeypatch.setattr(db_connector, "query_database", fake_query_database)
    monkeypatch.setattr(db_connector, "run_select", fake_run_select)

    connector = ConnectorConfig(
        name="Orders",
        slug="orders",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="db",
                name="DB",
                type="postgres",
                url="postgresql://localhost/test",
                table="orders",
                table_name="orders",
            )
        ],
        tools=[
            ToolDefinition(
                id="raw_orders",
                name="Raw orders",
                description="Raw-SQL tool",
                category="READ",
                source_ids=["db"],
                sql='SELECT * FROM "orders"',
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})

    assert calls == ["query_database"]
    assert result.rows[0]["status"] == "open"
