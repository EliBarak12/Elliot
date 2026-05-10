"""Integration test: full connector build flow end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_core.connector.serializer import deserialize_connector
from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession


def _tool(mcp: FastMCP, name: str):
    return mcp._tool_manager._tools[name].fn


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    return create_elliot_server(session)


@pytest.fixture()
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "customers.csv"
    p.write_text("id,name,region\n1,Alice,East\n2,Bob,West\n3,Carol,East\n")
    return p


def test_full_build_flow(mcp: FastMCP, session: ElliotSession, tmp_path: Path, csv_file: Path):
    # 1. Set product context
    r = _tool(mcp, "elliot_set_context")(name="TestCo", description="E-commerce platform")
    assert r["status"] == "ok"

    # 2. Discover CSV source
    r = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_file)},
        name="customers",
    )
    assert "source_id" in r

    # 3. Create SQL tool
    r = _tool(mcp, "elliot_create_tool")(
        name="count_customers",
        description="Returns the total number of customers in the system",
        category="AGGREGATE",
        sql='SELECT COUNT(*) as total FROM "customers"',
        parameters=[],
    )
    assert r["status"] == "created"
    tool_id = r["tool_id"]

    # 4. Preview tool — should execute SQL against loaded data
    r = _tool(mcp, "elliot_preview_tool")(tool_id=tool_id, params={})
    assert r["row_count"] == 1
    assert int(r["rows"][0]["total"]) == 3

    # 5. Build connector with selected tool
    r = _tool(mcp, "elliot_build_connector")(
        name="TestCo Connector",
        slug="testco",
        version="1.0.0",
        tool_ids=[tool_id],
        skill_ids=[],
    )
    assert r["status"] == "built"
    assert r["tool_count"] == 1

    # 6. Export connector to file
    export_path = str(tmp_path / "connector.json")
    r = _tool(mcp, "elliot_export_connector")(path=export_path)
    assert r["status"] == "exported"
    assert Path(export_path).exists()

    # 7. Verify exported file is valid
    config = deserialize_connector(Path(export_path).read_text())
    assert len(config.tools) == 1
    assert config.tools[0].name == "count_customers"
    assert config.name == "TestCo Connector"


def test_session_state_throughout_flow(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, csv_file: Path
):
    state = _tool(mcp, "elliot_get_session_state")()
    assert state["source_count"] == 0

    _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": str(csv_file)}, name="customers"
    )
    _tool(mcp, "elliot_create_tool")(
        name="list_customers",
        description="Returns all customer records from the database",
        category="READ",
        sql='SELECT * FROM "customers"',
        parameters=[],
    )

    state = _tool(mcp, "elliot_get_session_state")()
    assert state["source_count"] == 1
    assert state["tool_count"] == 1
    assert state["connector_built"] is False

    _tool(mcp, "elliot_build_connector")(name="C", slug="c", version="1.0.0")
    state = _tool(mcp, "elliot_get_session_state")()
    assert state["connector_built"] is True


def test_list_sources_list_tools_list_tables_consistent(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, csv_file: Path
):
    _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": str(csv_file)}, name="customers"
    )
    _tool(mcp, "elliot_create_tool")(
        name="all_customers",
        description="Returns every customer row from the data store",
        category="READ",
        sql='SELECT * FROM "customers"',
        parameters=[],
    )

    sources = _tool(mcp, "elliot_list_sources")()
    assert sources["count"] == 1

    tools = _tool(mcp, "elliot_list_tools")()
    assert tools["count"] == 1

    tables = _tool(mcp, "elliot_list_tables")()
    assert "customers" in tables["tables"]
