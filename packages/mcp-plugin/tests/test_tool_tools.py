"""Tests for tool MCP tools: create, get, update, list, delete, preview."""

from __future__ import annotations

import asyncio
import inspect
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


def _load_table(session: ElliotSession, tmp_path: Path) -> None:
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "orders.csv"
    p.write_text("id,amount\n1,100\n2,200\n3,300\n")
    _tool(s, "elliot_discover_source")(source_type="file", config={"path": str(p)}, name="orders")


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


def test_create_tool_slugifies_free_text_name(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    # A natural name with spaces must become a snake_case id, not a raw id with
    # spaces (which blew up downstream as [Errno 22] on Windows).
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="List Orders",
        description="Return all orders in the system",
        category="read",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    assert result["tool_id"] == "list_orders"


def test_create_tool_rejects_unsluggable_name(mcp: FastMCP, session: ElliotSession):
    result = _tool(mcp, "elliot_create_tool")(
        name="!!!",
        description="Return all orders in the system",
        category="read",
        sql="SELECT 1",
        parameters=[],
    )
    # No letters survive slugification -> actionable validation error, not a crash.
    blob = result.get("text", "") + result.get("error", "")
    assert "INVALID_TOOL_NAME" in blob or "valid tool id" in blob


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
    # SQL is stored in session.tool_sql, not on the model — the list endpoint
    # must merge it in so the Studio editor can render the query.
    assert result["tools"][0]["sql"] == 'SELECT * FROM "orders"'


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


def test_update_tool_reinfers_source_ids_when_sql_changes(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Regression: changing a tool's SQL to reference a different source must
    re-infer source_ids. Otherwise the tool keeps the old source_ids, the
    runtime materializes the wrong tables, and the SQL hits "no such table" /
    returns 0 rows at call time while lint stays green (the data.gov.il bug)."""
    _load_table(session, tmp_path)  # source "orders"

    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p2 = tmp_path / "customers.csv"
    p2.write_text("id,name\n1,Ann\n2,Bob\n")
    _tool(s, "elliot_discover_source")(
        source_type="file", config={"path": str(p2)}, name="customers"
    )

    orders_sid = next(sid for sid, src in session.sources.items() if src.name == "orders")
    customers_sid = next(sid for sid, src in session.sources.items() if src.name == "customers")

    _tool(mcp, "elliot_create_tool")(
        name="repointed",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    assert session.registry.get("repointed").source_ids == [orders_sid]

    _tool(mcp, "elliot_update_tool")(
        tool_id="repointed",
        patch={"sql": 'SELECT * FROM "customers"'},
    )

    # source_ids must now follow the SQL to the customers source.
    assert session.registry.get("repointed").source_ids == [customers_sid]


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


# ── Bug #2 regression: accept arguments/parameters aliases ───────────────────


def test_preview_tool_accepts_arguments_alias(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="orders_by_amount",
        description="Return orders with amount above threshold",
        category="READ",
        sql='SELECT * FROM "orders" WHERE amount > :threshold',
        parameters=[
            {"name": "threshold", "type": "integer", "required": True, "description": "min"}
        ],
    )
    result = _tool(mcp, "elliot_preview_tool")(
        tool_id="orders_by_amount", arguments={"threshold": 1}
    )
    assert "row_count" in result


def test_preview_tool_accepts_parameters_alias(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="orders_all",
        description="Return all orders",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="orders_all", parameters={})
    assert result["row_count"] == 3


# ── Bug #3 regression: structured VALIDATION_REQUIRED for missing required ───


def test_preview_tool_missing_required_returns_structured_error(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="orders_by_status",
        description="Return orders for the given status",
        category="READ",
        sql='SELECT * FROM "orders" WHERE status = :status',
        parameters=[
            {"name": "status", "type": "string", "required": True, "description": "status"}
        ],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="orders_by_status", params={})
    # to_mcp_error_content returns {"type": "text", "text": "[CODE] msg"}
    assert "VALIDATION_REQUIRED" in result.get("text", "")
    assert "status" in result.get("text", "")


# ── elliot_validate_tool accepts the same shape as elliot_create_tool ────────


def test_validate_tool_accepts_create_tool_shape(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Regression: elliot_validate_tool used to reject inputs that
    elliot_create_tool would happily accept (missing `id`, lowercase
    `category`)."""
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_validate_tool")(
        tool={
            "name": "orders_by_status",
            "description": "Return orders for the given status filter",
            "category": "read",
            "source_ids": list(session.sources.keys()),
            "parameters": [
                {"name": "status", "type": "string", "required": False, "description": "status"}
            ],
        }
    )
    assert result == {"valid": True}


def test_validate_tool_still_rejects_genuinely_invalid_input(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_validate_tool")(
        tool={
            "name": "x",  # too generic and description too short
            "description": "short",
            "category": "read",
            "source_ids": list(session.sources.keys()),
            "parameters": [],
        }
    )
    assert result["valid"] is False
    assert "error" in result
