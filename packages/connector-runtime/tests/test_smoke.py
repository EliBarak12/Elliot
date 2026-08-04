"""Tests for the publish-time smoke test (smoke.py)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import respx
from httpx import Response

from elliot_connector_runtime import smoke as smoke_mod
from elliot_connector_runtime.executor import ToolExecutor
from elliot_connector_runtime.smoke import (
    SMOKE_TIMEOUT_CODE,
    build_smoke_executor,
    smoke_arguments,
    smoke_test_connector,
)
from elliot_core.types import (
    ApiRequestMapping,
    ConnectorConfig,
    ParameterDefinition,
    SourceConfig,
    ToolDefinition,
)

_ROWS = [
    {"id": 1, "name": "Ada", "city": "London"},
    {"id": 2, "name": "Grace", "city": "Arlington"},
]


def _file_source(source_id: str = "people") -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name="People",
        type="file",
        format="json",
        content=json.dumps(_ROWS),
    )


def _read_tool(
    tool_id: str = "list_people",
    sql: str = 'SELECT id, name FROM "people" ORDER BY id',
    parameters: list[ParameterDefinition] | None = None,
    source_ids: list[str] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id.replace("_", " ").title(),
        description="List the registered people with their ids and names.",
        category="READ",
        sql=sql,
        parameters=parameters or [],
        source_ids=source_ids if source_ids is not None else ["people"],
    )


def _connector(
    tools: list[ToolDefinition],
    sources: list[SourceConfig] | None = None,
) -> ConnectorConfig:
    return ConnectorConfig(
        name="Smoke Fixture",
        slug="smoke-fixture",
        version="1.0.0",
        sources=sources if sources is not None else [_file_source()],
        tools=tools,
        skills=[],
    )


def _run(config: ConnectorConfig, **kwargs: Any) -> Any:
    executor = ToolExecutor(config, {})
    return asyncio.run(smoke_test_connector(config, executor, **kwargs))


# ── smoke_arguments ──────────────────────────────────────────────────────────


def test_smoke_arguments_no_params() -> None:
    assert smoke_arguments(_read_tool()) == {}


def test_smoke_arguments_optional_params_omitted() -> None:
    tool = _read_tool(
        parameters=[
            ParameterDefinition(name="limit", type="integer", required=False, description="")
        ]
    )
    assert smoke_arguments(tool) == {}


def test_smoke_arguments_required_default_filled() -> None:
    tool = _read_tool(
        parameters=[
            ParameterDefinition(
                name="limit", type="integer", required=True, default=5, description=""
            )
        ]
    )
    assert smoke_arguments(tool) == {"limit": 5}


def test_smoke_arguments_required_enum_uses_first_value() -> None:
    tool = _read_tool(
        parameters=[
            ParameterDefinition(
                name="status",
                type="string",
                required=True,
                enum=["open", "closed"],
                description="",
            )
        ]
    )
    assert smoke_arguments(tool) == {"status": "open"}


def test_smoke_arguments_unfillable_required_returns_none() -> None:
    tool = _read_tool(
        parameters=[
            ParameterDefinition(name="user_id", type="integer", required=True, description="")
        ]
    )
    assert smoke_arguments(tool) is None


# ── registration smoke ───────────────────────────────────────────────────────


def test_healthy_connector_passes() -> None:
    report = _run(_connector([_read_tool()]))
    assert report.passed
    assert "list_people" in report.listed_tools
    # Connecting always costs context: the serialized tools/list estimate.
    assert report.context_tokens > 0
    assert report.missing_tools == []
    [result] = report.tool_results
    assert result.status == "passed"
    assert result.rows == 2
    assert "ok" in report.summary()


def test_registration_error_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(config: Any, executor: Any) -> tuple[list[str], int]:
        raise RuntimeError("schema generation exploded")

    monkeypatch.setattr(smoke_mod, "_build_and_list", _boom)
    report = _run(_connector([_read_tool()]))
    assert not report.passed
    assert report.registration_error == "schema generation exploded"
    assert "failed to register" in report.summary()


def test_missing_tool_fails_report(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _partial_list(config: Any, executor: Any) -> tuple[list[str], int]:
        return ["some_other_tool"], 0

    monkeypatch.setattr(smoke_mod, "_build_and_list", _partial_list)
    report = _run(_connector([_read_tool()]))
    assert not report.passed
    assert report.missing_tools == ["list_people"]
    # A tool that never registered is not executed on top of being missing.
    assert report.tool_results == []


# ── execute smoke ────────────────────────────────────────────────────────────


def test_bad_column_fails_execute_smoke() -> None:
    # The table exists (integrity-style static checks pass) but the column
    # does not — only executing the tool can catch this class.
    report = _run(_connector([_read_tool(sql='SELECT nonexistent_col FROM "people"')]))
    assert not report.passed
    [result] = report.tool_results
    assert result.status == "failed"
    assert result.error_code == "INVALID_SQL"


def test_missing_table_fails_execute_smoke() -> None:
    report = _run(_connector([_read_tool(sql='SELECT id FROM "ghosts"')]))
    assert not report.passed
    [result] = report.tool_results
    assert result.status == "failed"
    assert result.error_code == "TABLE_NOT_FOUND"
    assert "ghosts" in (result.reason or "")


@respx.mock
def test_upstream_404_fails_execute_smoke() -> None:
    respx.get("https://api.example.com/feed").mock(return_value=Response(404))
    source = SourceConfig(
        id="feed",
        name="Feed",
        type="rest",
        url="https://api.example.com/feed",
    )
    tool = ToolDefinition(
        id="list_feed",
        name="List feed",
        description="List the live feed items.",
        category="READ",
        rest_query_params=["limit"],
        parameters=[
            ParameterDefinition(name="limit", type="integer", required=False, description="")
        ],
        source_ids=["feed"],
    )
    report = _run(_connector([tool], sources=[source]))
    assert not report.passed
    [result] = report.tool_results
    assert result.status == "failed"
    assert result.error_code == "UPSTREAM_FETCH_FAILED"


@respx.mock
def test_write_tools_are_never_executed() -> None:
    route = respx.post("https://api.example.com/orders").mock(return_value=Response(200))
    source = SourceConfig(
        id="orders",
        name="Orders API",
        type="rest",
        url="https://api.example.com/orders",
    )
    tool = ToolDefinition(
        id="create_order",
        name="Create order",
        description="Create a new order upstream.",
        category="WRITE",
        api_mapping=ApiRequestMapping(method="POST", body_params=["sku"]),
        parameters=[ParameterDefinition(name="sku", type="string", required=True, description="")],
        source_ids=["orders"],
    )
    report = _run(_connector([tool], sources=[source]))
    assert report.passed  # skipped tools do not fail the smoke
    [result] = report.tool_results
    assert result.status == "skipped"
    assert "never executed" in (result.reason or "")
    assert not route.called


def test_unfillable_required_param_skips_not_fails() -> None:
    tool = _read_tool(
        sql='SELECT id FROM "people" WHERE id = :user_id',
        parameters=[
            ParameterDefinition(name="user_id", type="integer", required=True, description="")
        ],
    )
    report = _run(_connector([tool]))
    assert report.passed
    [result] = report.tool_results
    assert result.status == "skipped"
    assert "user_id" in (result.reason or "")


def test_required_enum_param_is_executed_with_first_value() -> None:
    tool = _read_tool(
        sql='SELECT id, city FROM "people" WHERE city = :city',
        parameters=[
            ParameterDefinition(
                name="city",
                type="string",
                required=True,
                enum=["London", "Arlington"],
                description="",
            )
        ],
    )
    report = _run(_connector([tool]))
    assert report.passed
    [result] = report.tool_results
    assert result.status == "passed"
    assert result.rows == 1


def test_timeout_reports_smoke_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _connector([_read_tool()])
    executor = ToolExecutor(config, {})

    async def _hang(tool: Any, arguments: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(executor, "execute", _hang)
    report = asyncio.run(smoke_test_connector(config, executor, tool_timeout_seconds=0.05))
    assert not report.passed
    [result] = report.tool_results
    assert result.status == "failed"
    assert result.error_code == SMOKE_TIMEOUT_CODE


def test_execute_false_lists_only() -> None:
    report = _run(
        _connector([_read_tool(sql='SELECT id FROM "ghosts"')]),
        execute=False,
    )
    # Broken SQL is not reached — only registration is checked.
    assert report.passed
    assert report.tool_results == []
    assert "list_people" in report.listed_tools


def _managed_connector() -> ConnectorConfig:
    source = SourceConfig(
        id="items",
        name="items",
        type="elliot",
        table_name="items",
        columns=[
            {"name": "title", "type": "string", "required": True},
            {"name": "done", "type": "boolean"},
        ],
    )
    tool = _read_tool(
        "list_items",
        sql='SELECT _id, title FROM "items" ORDER BY _created_at',
        source_ids=["items"],
    )
    return _connector([tool], sources=[source])


def _forbid_host_managed_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any resolution of the host managed-store path an immediate failure.

    This is the production bug class: on a host with a read-only working
    directory, merely resolving the default path and mkdir-ing its parent
    raises EACCES. Raising here proves the smoke never goes near it.
    """

    def _boom() -> str:
        raise AssertionError("smoke must not open the host managed store")

    monkeypatch.setattr("elliot_core.sqlite.managed_store.managed_db_path", _boom)


def test_managed_read_smokes_without_touching_host_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_host_managed_store(monkeypatch)
    config = _managed_connector()
    executor = build_smoke_executor(config, {})
    report = asyncio.run(smoke_test_connector(config, executor))
    assert report.passed
    [result] = report.tool_results
    assert result.status == "passed"
    # The smoke's private store is empty on purpose — it proves the query
    # path serves without reading real app data.
    assert result.rows == 0


def test_smoke_gives_bare_executor_a_memory_store(monkeypatch: pytest.MonkeyPatch) -> None:
    # A caller that builds its own executor without a managed store must not
    # fall through to the lazy on-disk default mid-smoke.
    _forbid_host_managed_store(monkeypatch)
    config = _managed_connector()
    report = asyncio.run(smoke_test_connector(config, ToolExecutor(config, {})))
    assert report.passed
    [result] = report.tool_results
    assert result.status == "passed"


def test_build_smoke_executor_skips_store_without_managed_sources() -> None:
    executor = build_smoke_executor(_connector([_read_tool()]), {})
    assert executor._managed_store is None


def test_empty_result_is_a_pass() -> None:
    report = _run(
        _connector([_read_tool(sql="SELECT id, name FROM \"people\" WHERE name = 'Nobody'")])
    )
    assert report.passed
    [result] = report.tool_results
    assert result.status == "passed"
    assert result.rows == 0
