"""Tests for tool MCP tools: create, get, update, list, delete, preview."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_tool_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):
    return mcp._tool_manager._tools[name].fn


def _load_table(session: ElliotSession, tmp_path: Path) -> None:
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "orders.csv"
    p.write_text("id,amount\n1,100\n2,200\n3,300\n")
    s._tool_manager._tools["elliot_discover_source"].fn(
        source_type="file", config={"path": str(p)}, name="orders"
    )


# ---------------------------------------------------------------------------
# elliot_create_tool
# ---------------------------------------------------------------------------


def test_create_tool_returns_tool_id(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="total_orders",
        description="Returns total order count",
        category="READ",
        sql='SELECT COUNT(*) as cnt FROM "orders"',
        parameters=[],
    )
    assert result["status"] == "created"
    assert result["tool_id"] == "total_orders"


def test_create_tool_stores_in_registry(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="sum_orders",
        description="Sum of all order amounts",
        category="READ",
        sql='SELECT SUM(amount) as total FROM "orders"',
        parameters=[],
    )
    assert session.registry.get("sum_orders") is not None
    assert session.tool_sql["sum_orders"] == 'SELECT SUM(amount) as total FROM "orders"'


def test_create_tool_aggregate_category_mapped(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="count_orders",
        description="Count all orders in the system",
        category="AGGREGATE",
        sql='SELECT COUNT(*) as cnt FROM "orders"',
        parameters=[],
    )
    assert result["status"] == "created"
    tool = session.registry.get("count_orders")
    assert tool is not None
    assert tool.category == "READ"


# ---------------------------------------------------------------------------
# elliot_get_tool
# ---------------------------------------------------------------------------


def test_get_tool_returns_definition_and_sql(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="get_orders",
        description="Retrieve all orders from system",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_get_tool")(tool_id="get_orders")
    assert result["id"] == "get_orders"
    assert result["sql"] == 'SELECT * FROM "orders"'


def test_get_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_tool")(tool_id="ghost")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# elliot_list_tools
# ---------------------------------------------------------------------------


def test_list_tools_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_list_tools")()
    assert result["count"] == 0


def test_list_tools_after_create(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="list_orders",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_list_tools")()
    assert result["count"] == 1
    assert result["tools"][0]["id"] == "list_orders"


# ---------------------------------------------------------------------------
# elliot_delete_tool
# ---------------------------------------------------------------------------


def test_delete_tool_removes_from_registry(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="del_orders",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_delete_tool")(tool_id="del_orders")
    assert result["status"] == "deleted"
    assert session.registry.get("del_orders") is None
    assert "del_orders" not in session.tool_sql


def test_delete_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_delete_tool")(tool_id="nonexistent")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# elliot_update_tool
# ---------------------------------------------------------------------------


def test_update_tool_sql(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="upd_orders",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    _tool(mcp, "elliot_update_tool")(
        tool_id="upd_orders",
        patch={"sql": 'SELECT COUNT(*) as cnt FROM "orders"'},
    )
    assert session.tool_sql["upd_orders"] == 'SELECT COUNT(*) as cnt FROM "orders"'


def test_update_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_update_tool")(tool_id="ghost", patch={"sql": "SELECT 1"})
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# elliot_preview_tool
# ---------------------------------------------------------------------------


def test_preview_tool_returns_rows(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="preview_orders",
        description="Retrieve all orders from the system",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="preview_orders", params={})
    assert result["row_count"] == 3


def test_preview_tool_aggregate(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="total_amount",
        description="Returns the total sum of all orders",
        category="AGGREGATE",
        sql='SELECT SUM(amount) as total FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="total_amount", params={})
    assert result["row_count"] == 1


def test_preview_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_preview_tool")(tool_id="ghost", params={})
    assert "text" in result or "error" in result
