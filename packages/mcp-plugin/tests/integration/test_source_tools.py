"""Integration tests for source MCP tools — no HTTP server required."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


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
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "customers.csv"
    p.write_text("id,name,city\n1,Alice,NY\n2,Bob,LA\n3,Carol,SF\n")
    return p


def test_discover_csv_source(mcp: FastMCP, session: ElliotSession, csv_file: Path):
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_file)},
        name="customers",
    )
    assert "source_id" in result
    assert result["row_count"] == 3
    assert len(session.engine.get_table_names()) > 0


def test_list_sources(mcp: FastMCP, session: ElliotSession, csv_file: Path):
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_file)},
        name="customers",
    )
    result = _tool(mcp, "elliot_list_sources")()
    assert result["count"] == 1
    assert result["sources"][0]["name"] == "customers"


def test_preview_source_rows(mcp: FastMCP, session: ElliotSession, csv_file: Path):
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_file)},
        name="customers",
    )
    result = _tool(mcp, "elliot_preview_source")(table_name="customers", limit=2)
    assert result["row_count"] == 2
    assert len(result["rows"]) == 2


def test_remove_source_drops_table(mcp: FastMCP, session: ElliotSession, csv_file: Path):
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_file)},
        name="customers",
    )
    assert len(session.engine.get_table_names()) == 1

    _tool(mcp, "elliot_remove_source")(source_id=disc["source_id"])
    assert len(session.engine.get_table_names()) == 0

    lst = _tool(mcp, "elliot_list_sources")()
    assert lst["count"] == 0


def test_discover_json_source(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps([{"order_id": 1, "amount": 99.9}, {"order_id": 2, "amount": 50.0}]))
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(p), "format": "json"},
        name="orders",
    )
    assert result["row_count"] == 2


def test_profile_source(mcp: FastMCP, session: ElliotSession, csv_file: Path):
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_file)},
        name="customers",
    )
    result = _tool(mcp, "elliot_profile_source")(table_name="customers")
    assert result["table"] == "customers"
    assert result["row_count"] == 3
    assert "name" in result["columns"]
