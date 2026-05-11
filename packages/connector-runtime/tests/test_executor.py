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
from elliot_core.types import ConnectorConfig, ParameterDefinition, SourceConfig, ToolDefinition

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
