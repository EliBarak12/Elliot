"""Tests for ToolExecutor: covers READ, WRITE, passthrough, coerce, rename paths."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from elliot_core.errors import ElliotError, NotFoundError, SourceFetchError
from elliot_core.tools.executor import (
    ToolExecutor,
    _apply_rename,
    _coerce,
    _coerce_and_validate,
)
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import FetchResult, SourceConfig
from elliot_core.types.tool import (
    ApiRequestMapping,
    ParameterDefinition,
    ResponseShape,
    ToolDefinition,
)


def _make_source(type_: str = "rest", url: str = "https://api.example.com/items") -> SourceConfig:
    return SourceConfig(id="src", name="Source", type=type_, url=url)


def _make_read_tool(
    source_id: str = "src",
    params: list[ParameterDefinition] | None = None,
    rest_query_params: list[str] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        id="list_items",
        name="List items",
        description="Return all items",
        category="READ",
        source_ids=[source_id],
        parameters=params or [],
        rest_query_params=rest_query_params or [],
    )


def _make_write_tool(source_id: str = "src") -> ToolDefinition:
    return ToolDefinition(
        id="create_item",
        name="Create item",
        description="Create an item",
        category="WRITE",
        source_ids=[source_id],
        parameters=[
            ParameterDefinition(name="name", type="string", required=True, description="Name")
        ],
        api_mapping=ApiRequestMapping(
            method="POST",
            path_template="/items",
            body_params=["name"],
            body_format="json",
        ),
    )


def _make_config(
    source: SourceConfig | None = None,
    tools: list[ToolDefinition] | None = None,
) -> ConnectorConfig:
    src = source or _make_source()
    return ConnectorConfig(
        name="Test",
        slug="test",
        version="1.0.0",
        sources=[src],
        tools=tools or [_make_read_tool()],
    )


def _fake_fetch(rows: list[dict[str, Any]]) -> Any:
    async def _fn(source: SourceConfig, secrets: dict[str, str]) -> FetchResult:
        return FetchResult(rows=rows, fetched_at="2024-01-01T00:00:00Z")

    return _fn


# ── _coerce helper ────────────────────────────────────────────────────────────


def test_coerce_integer():
    assert _coerce("42", "integer") == 42


def test_coerce_integer_invalid():
    with pytest.raises(ElliotError) as exc_info:
        _coerce("abc", "integer")
    assert exc_info.value.code == "INVALID_PARAM_TYPE"


def test_coerce_number():
    assert _coerce("3.14", "number") == 3.14


def test_coerce_number_invalid():
    with pytest.raises(ElliotError) as exc_info:
        _coerce("abc", "number")
    assert exc_info.value.code == "INVALID_PARAM_TYPE"


def test_coerce_boolean():
    assert _coerce(1, "boolean") is True


def test_coerce_boolean_from_string():
    assert _coerce("true", "boolean") is True
    assert _coerce("False", "boolean") is False
    assert _coerce("1", "boolean") is True
    assert _coerce("off", "boolean") is False


def test_coerce_boolean_invalid_string():
    with pytest.raises(ElliotError) as exc_info:
        _coerce("maybe", "boolean")
    assert exc_info.value.code == "INVALID_PARAM_TYPE"


def test_coerce_string_passthrough():
    assert _coerce("hello", "string") == "hello"


def test_coerce_string_rejects_non_string():
    # A string param given an int must error, not silently become "99"
    # (otherwise SQL binds the wrong type and returns empty results).
    with pytest.raises(ElliotError) as exc_info:
        _coerce(99, "string")
    assert exc_info.value.code == "INVALID_PARAM_TYPE"


def test_coerce_and_validate_rejects_unknown_param():
    # Wrong-cased / typo'd parameter names are rejected instead of silently
    # dropped (which used to bind NULL and return 200 + empty rows).
    tool = _make_read_tool(
        params=[ParameterDefinition(name="iso", type="string", required=True, description="ISO")]
    )
    with pytest.raises(ElliotError) as exc_info:
        _coerce_and_validate(tool, {"ISO": "JP"})
    assert exc_info.value.code == "UNKNOWN_PARAM"


def test_coerce_and_validate_allows_rest_query_params():
    # rest_query_params are valid call-time keys even when not also declared
    # in `parameters`, so passthrough tools must not be rejected.
    tool = _make_read_tool(rest_query_params=["q"])
    assert _coerce_and_validate(tool, {"q": "widget"}) == {}


def test_coerce_and_validate_enforces_enum():
    tool = _make_read_tool(
        params=[
            ParameterDefinition(
                name="status", type="string", required=True, description="S", enum=["open", "shut"]
            )
        ]
    )
    assert _coerce_and_validate(tool, {"status": "open"})["status"] == "open"
    with pytest.raises(ElliotError) as exc_info:
        _coerce_and_validate(tool, {"status": "sideways"})
    assert exc_info.value.code == "INVALID_PARAM_VALUE"


# ── _coerce_and_validate ──────────────────────────────────────────────────────


def test_coerce_and_validate_missing_required():
    tool = _make_read_tool(
        params=[ParameterDefinition(name="q", type="string", required=True, description="Query")]
    )
    with pytest.raises(ElliotError) as exc_info:
        _coerce_and_validate(tool, {})
    assert exc_info.value.code == "MISSING_PARAM"


def test_coerce_and_validate_uses_default():
    tool = _make_read_tool(
        params=[
            ParameterDefinition(
                name="limit", type="integer", required=False, description="Limit", default=10
            )
        ]
    )
    result = _coerce_and_validate(tool, {})
    assert result["limit"] == 10


def test_coerce_and_validate_explicit_none_uses_default():
    # The MCP layer surfaces an omitted optional parameter as an explicit
    # None; it must still fall back to the declared default rather than bind
    # NULL (which makes `LIMIT :limit` raise a datatype mismatch).
    tool = _make_read_tool(
        params=[
            ParameterDefinition(
                name="limit", type="integer", required=False, description="Limit", default=10
            )
        ]
    )
    assert _coerce_and_validate(tool, {"limit": None})["limit"] == 10


def test_coerce_and_validate_skips_none_optional():
    tool = _make_read_tool(
        params=[ParameterDefinition(name="q", type="string", required=False, description="Q")]
    )
    result = _coerce_and_validate(tool, {})
    assert "q" not in result


# ── _apply_rename ─────────────────────────────────────────────────────────────


def test_apply_rename_empty():
    rows = [{"id": 1, "name": "Alice"}]
    assert _apply_rename(rows, {}) == rows


def test_apply_rename_renames_keys():
    rows = [{"id": 1, "name": "Alice"}]
    result = _apply_rename(rows, {"name": "full_name"})
    assert result == [{"id": 1, "full_name": "Alice"}]


# ── ToolExecutor.execute ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_tool_not_found():
    executor = ToolExecutor(_make_config())
    with pytest.raises(NotFoundError):
        await executor.execute("nonexistent", {})


@pytest.mark.asyncio
async def test_execute_read_full_returns_rows():
    rows = [{"id": 1, "name": "Widget"}]
    executor = ToolExecutor(_make_config(), fetch_source=_fake_fetch(rows))
    result = await executor.execute("list_items", {})
    # Flattener now stamps every row with ``_id`` for cross-table joins; the
    # business columns must still survive intact, so compare the projected
    # subset rather than strict-equality.
    assert [{k: v for k, v in r.items() if not k.startswith("_")} for r in result.rows] == rows
    assert result.meta["fetch_mode"] == "full"


@pytest.mark.asyncio
async def test_execute_read_truncates_at_max_rows():
    rows = [{"id": i} for i in range(200)]
    tool = ToolDefinition(
        id="list_items",
        name="List items",
        description="desc",
        category="READ",
        source_ids=["src"],
        response_shape=ResponseShape(max_rows=5),
    )
    config = _make_config(tools=[tool])
    executor = ToolExecutor(config, fetch_source=_fake_fetch(rows))
    result = await executor.execute("list_items", {})
    assert len(result.rows) == 5
    assert result.meta["truncated"] is True


@pytest.mark.asyncio
async def test_execute_read_applies_rename():
    rows = [{"id": 1, "nm": "Widget"}]
    tool = ToolDefinition(
        id="list_items",
        name="List items",
        description="desc",
        category="READ",
        source_ids=["src"],
        response_shape=ResponseShape(rename={"nm": "name"}),
    )
    config = _make_config(tools=[tool])
    executor = ToolExecutor(config, fetch_source=_fake_fetch(rows))
    result = await executor.execute("list_items", {})
    assert result.rows[0]["name"] == "Widget"


@pytest.mark.asyncio
async def test_fetch_sources_wraps_exception():
    async def _fail(source: SourceConfig, secrets: dict[str, str]) -> FetchResult:
        raise RuntimeError("network down")

    executor = ToolExecutor(_make_config(), fetch_source=_fail)
    with pytest.raises(SourceFetchError):
        await executor.execute("list_items", {})


# ── tool.sql precedence (regression: Bug #4) ─────────────────────────────────


@pytest.mark.asyncio
async def test_execute_read_uses_tool_sql_when_set():
    """When tool.sql is set, the executor runs that SQL instead of generating
    one from filter_groups/return_fields. Without this, tools created via the
    agentic-builder MCP path are run as `SELECT * FROM <source>` regardless
    of the actual SQL the user wrote.
    """
    rows = [
        {"id": 1, "plan": "pro", "name": "Alice"},
        {"id": 2, "plan": "starter", "name": "Bob"},
        {"id": 3, "plan": "pro", "name": "Carol"},
    ]
    source = SourceConfig(id="src", name="customers", type="file", path="x.json")
    source.table_name = "customers"
    tool = ToolDefinition(
        id="find_by_plan",
        name="find_by_plan",
        description="filter customers by plan",
        category="READ",
        source_ids=["src"],
        sql="SELECT id, name FROM customers WHERE plan = :plan ORDER BY id",
        parameters=[ParameterDefinition(name="plan", type="string", required=True)],
    )
    config = ConnectorConfig(name="t", slug="t", version="1.0.0", sources=[source], tools=[tool])
    executor = ToolExecutor(config, fetch_source=_fake_fetch(rows))
    result = await executor.execute("find_by_plan", {"plan": "pro"})
    assert [r["id"] for r in result.rows] == [1, 3]
    # The SELECT projection drops the 'plan' column.
    assert "plan" not in result.rows[0]


@pytest.mark.asyncio
async def test_execute_read_uses_source_table_name_for_sqlite():
    """The executor must ingest each source under its discovered table_name
    so user SQL like `FROM customers` resolves regardless of source_id (which
    may be a UUID when running from a Studio session).
    """
    rows = [{"id": 1, "amount": 100}]
    source = SourceConfig(id="uuid-abc", name="orders", type="file", path="x.json")
    source.table_name = "orders"
    tool = ToolDefinition(
        id="t",
        name="t",
        description="d",
        category="READ",
        source_ids=["uuid-abc"],
        sql="SELECT SUM(amount) AS total FROM orders",
    )
    config = ConnectorConfig(name="t", slug="t", version="1.0.0", sources=[source], tools=[tool])
    executor = ToolExecutor(config, fetch_source=_fake_fetch(rows))
    result = await executor.execute("t", {})
    # Aggregation rows don't carry parent ``_id``/``_parent_id`` (the GROUP
    # BY collapses the source rows), but defensively project just the
    # business columns the test cares about.
    assert [{k: v for k, v in r.items() if not k.startswith("_")} for r in result.rows] == [
        {"total": 100}
    ]


# ── Passthrough mode ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_execute_read_passthrough():
    respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1, "name": "Widget"}])
    )
    tool = _make_read_tool(rest_query_params=["q"])
    config = _make_config(tools=[tool])
    executor = ToolExecutor(config)
    result = await executor.execute("list_items", {"q": "widget"})
    assert result.meta["fetch_mode"] == "passthrough"
    assert len(result.rows) == 1


@pytest.mark.asyncio
async def test_passthrough_non_rest_source_raises():
    tool = ToolDefinition(
        id="list_items",
        name="List items",
        description="desc",
        category="READ",
        source_ids=["src"],
        rest_query_params=["q"],
    )
    config = _make_config(source=_make_source(type_="file"), tools=[tool])
    executor = ToolExecutor(config)
    with pytest.raises(ElliotError) as exc_info:
        await executor.execute("list_items", {"q": "x"})
    assert exc_info.value.code == "INVALID_TOOL"


# ── WRITE mode ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_execute_write_success():
    respx.post("https://api.example.com/items").mock(
        return_value=Response(200, json={"id": 99, "name": "NewWidget"})
    )
    tool = _make_write_tool()
    config = _make_config(source=_make_source(url="https://api.example.com"), tools=[tool])
    executor = ToolExecutor(config)
    result = await executor.execute("create_item", {"name": "NewWidget"})
    assert result.meta["fetch_mode"] == "write"
    assert result.rows[0]["id"] == 99


@pytest.mark.asyncio
@respx.mock
async def test_execute_write_http_error():
    respx.post("https://api.example.com/items").mock(return_value=Response(400))
    tool = _make_write_tool()
    config = _make_config(source=_make_source(url="https://api.example.com"), tools=[tool])
    executor = ToolExecutor(config)
    with pytest.raises(ElliotError) as exc_info:
        await executor.execute("create_item", {"name": "X"})
    assert exc_info.value.code == "API_REQUEST_FAILED"


@pytest.mark.asyncio
async def test_execute_write_missing_api_mapping():
    tool = ToolDefinition(
        id="create_item",
        name="Create item",
        description="desc",
        category="WRITE",
        source_ids=["src"],
        parameters=[],
    )
    config = _make_config(tools=[tool])
    executor = ToolExecutor(config)
    with pytest.raises(ElliotError) as exc_info:
        await executor.execute("create_item", {})
    assert exc_info.value.code == "MISSING_API_MAPPING"


@pytest.mark.asyncio
async def test_execute_write_empty_source_ids():
    """A WRITE tool with no source_ids raises ElliotError, not IndexError."""
    tool = _make_write_tool()
    tool.source_ids = []
    config = _make_config(source=_make_source(url="https://api.example.com"), tools=[tool])
    executor = ToolExecutor(config)
    with pytest.raises(ElliotError) as exc_info:
        await executor.execute("create_item", {"name": "X"})
    assert exc_info.value.code == "INVALID_TOOL"
