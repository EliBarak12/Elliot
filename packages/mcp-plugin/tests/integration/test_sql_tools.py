"""Integration tests for SQL MCP tools — no HTTP server required."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def _tool(mcp: FastMCP, name: str):
    return mcp._tool_manager._tools[name].fn


@pytest.fixture(autouse=True)
def load_table(mcp: FastMCP, session: ElliotSession, tmp_path: Path) -> None:
    """Pre-load a CSV table into every test in this module."""
    p = tmp_path / "products.csv"
    p.write_text("id,name,price\n1,Widget,9.99\n2,Gadget,19.99\n3,Doohickey,4.99\n")
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(p)},
        name="products",
    )


def test_query_sql_returns_rows(mcp: FastMCP):
    result = _tool(mcp, "elliot_query_sql")(sql='SELECT * FROM "products"')
    assert result["row_count"] == 3


def test_query_sql_with_filter(mcp: FastMCP):
    result = _tool(mcp, "elliot_query_sql")(
        sql='SELECT * FROM "products" WHERE id = :id', params={"id": "1"}
    )
    assert result["row_count"] == 1


def test_query_sql_drop_rejected(mcp: FastMCP):
    result = _tool(mcp, "elliot_query_sql")(sql='DROP TABLE "products"')
    assert "text" in result or "error" in result


def test_validate_sql_select_valid(mcp: FastMCP):
    result = _tool(mcp, "elliot_validate_sql")(sql='SELECT name FROM "products"')
    assert result["valid"] is True


def test_validate_sql_delete_invalid(mcp: FastMCP):
    result = _tool(mcp, "elliot_validate_sql")(sql='DELETE FROM "products"')
    assert result["valid"] is False


def test_get_schema_returns_products(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_schema")()
    assert "products" in result
    col_names = [c["name"] for c in result["products"]]
    assert "id" in col_names
    assert "name" in col_names
    assert "price" in col_names


def test_sample_data_returns_rows(mcp: FastMCP):
    result = _tool(mcp, "elliot_sample_data")(table_name="products", limit=2)
    assert "rows" in result
    assert len(result["rows"]) <= 2


def test_explain_query(mcp: FastMCP):
    result = _tool(mcp, "elliot_explain_query")(sql='SELECT * FROM "products"')
    assert "plan" in result


def test_profile_column(mcp: FastMCP):
    result = _tool(mcp, "elliot_profile_column")(table_name="products", column_name="name")
    assert isinstance(result, dict)
    assert "error" not in result
