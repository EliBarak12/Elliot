"""Integration test: full connector build flow end-to-end."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_core.connector.serializer import deserialize_connector
from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession

# CLAUDE.md: integration tests carry pytest.mark.integration so the suite
# can be selected/deselected via `-m integration` / `-m "not integration"`.
pytestmark = pytest.mark.integration


def _tool(mcp: FastMCP, name: str):
    fn = mcp._tool_manager._tools[name].fn
    if inspect.iscoroutinefunction(fn):
        try:
            asyncio.get_running_loop()
            return fn
        except RuntimeError:

            def sync_wrapper(*args, **kwargs):
                return asyncio.run(fn(*args, **kwargs))

            return sync_wrapper
    return fn


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


def test_build_connector_sets_and_preserves_instructions(
    mcp: FastMCP, session: ElliotSession, csv_file: Path
):
    """The agent can author connector-level instructions, and a later rebuild
    that omits them preserves the previously-set guidance."""
    _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": str(csv_file)}, name="customers"
    )
    r = _tool(mcp, "elliot_create_tool")(
        name="list_customers",
        description="Returns all customer records from the database",
        category="READ",
        sql='SELECT * FROM "customers"',
        parameters=[],
    )
    tool_id = r["tool_id"]

    guidance = "Call list_customers first; results are capped at 100 rows."
    r = _tool(mcp, "elliot_build_connector")(
        name="TestCo Connector",
        slug="testco",
        version="1.0.0",
        instructions=guidance,
        tool_ids=[tool_id],
    )
    assert r["status"] == "built"
    assert session.connector is not None
    assert session.connector.instructions == guidance

    # Rebuild without instructions — the prior guidance must survive.
    _tool(mcp, "elliot_build_connector")(
        name="TestCo Connector", slug="testco", version="1.0.0", tool_ids=[tool_id]
    )
    assert session.connector.instructions == guidance


def test_export_is_blocked_on_lint_error(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, csv_file: Path
):
    """Export is a contract gate: a connector with a lint ERROR must not ship."""
    _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": str(csv_file)}, name="customers"
    )
    # Verb-first but < 15 chars -> DESCRIPTION_TOO_SHORT (ERROR).
    r = _tool(mcp, "elliot_create_tool")(
        name="count_customers",
        description="Get count",
        category="AGGREGATE",
        sql='SELECT COUNT(*) as total FROM "customers"',
        parameters=[],
    )
    assert r["status"] == "created"
    _tool(mcp, "elliot_build_connector")(name="C", slug="c", version="1.0.0")

    export_path = str(tmp_path / "connector.json")
    r = _tool(mcp, "elliot_export_connector")(path=export_path)
    assert "EXPORT_LINT_FAILED" in r["text"]  # to_mcp_error_content shape: {type, text}
    # Errors are absolute — allow_warnings must NOT let an error through.
    r2 = _tool(mcp, "elliot_export_connector")(path=export_path, allow_warnings=True)
    assert "EXPORT_LINT_FAILED" in r2["text"]
    assert not Path(export_path).exists()  # nothing written on a failed gate


def test_export_warnings_block_by_default_but_can_be_allowed(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, csv_file: Path
):
    """Warnings block export by default; allow_warnings=true ships with them."""
    _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": str(csv_file)}, name="customers"
    )
    # >=15 chars but does NOT start with a verb -> DESCRIPTION_MISSING_VERB (WARN).
    _tool(mcp, "elliot_create_tool")(
        name="customer_total",
        description="Total customers across every region in the store",
        category="AGGREGATE",
        sql='SELECT COUNT(*) as total FROM "customers"',
        parameters=[],
    )
    _tool(mcp, "elliot_build_connector")(name="C", slug="c", version="1.0.0")
    export_path = str(tmp_path / "connector.json")

    blocked = _tool(mcp, "elliot_export_connector")(path=export_path)
    assert "EXPORT_LINT_FAILED" in blocked["text"]
    assert not Path(export_path).exists()

    ok = _tool(mcp, "elliot_export_connector")(path=export_path, allow_warnings=True)
    assert ok["status"] == "exported"
    assert ok["lint"]["warnings"] >= 1
    assert Path(export_path).exists()


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
