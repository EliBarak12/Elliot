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


async def test_executor_no_sql_raises() -> None:
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
    with pytest.raises(ExecutorError, match="no sql defined"):
        await executor.execute(tool, {})


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
