"""Tests for skill, context, and connector MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
from elliot_mcp_plugin.tools.context_tools import register_context_tools
from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_skill_tools(server, session)
    register_context_tools(server, session)
    register_connector_tools(server, session)
    register_tool_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):
    return mcp._tool_manager._tools[name].fn


def _load_and_create_tool(mcp: FastMCP, session: ElliotSession, tmp_path: Path) -> str:
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "items.csv"
    p.write_text("id,val\n1,a\n2,b\n")
    s._tool_manager._tools["elliot_discover_source"].fn(
        source_type="file", config={"path": str(p)}, name="items"
    )
    r = _tool(mcp, "elliot_create_tool")(
        name="count_items",
        description="Returns the count of all items in stock",
        category="READ",
        sql='SELECT COUNT(*) as cnt FROM "items"',
        parameters=[],
    )
    return r["tool_id"]


# ---------------------------------------------------------------------------
# skill tools
# ---------------------------------------------------------------------------


def test_list_skills_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_list_skills")()
    assert result["count"] == 0


def test_create_skill_unknown_tool_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_create_skill")(
        name="my_skill",
        description="Does something useful",
        steps=[{"alias": "step1", "tool_id": "nonexistent_tool", "params": {}}],
        input_parameters=[],
    )
    assert "error" in result


def test_create_skill_registers(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_create_skill")(
        name="item_count_skill",
        description="Counts all items in a single step",
        steps=[{"alias": "count", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    assert result["status"] == "created"
    skill_id = result["skill_id"]
    assert session.registry.get_skill(skill_id) is not None


def test_list_skills_after_create(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    _tool(mcp, "elliot_create_skill")(
        name="list_skill",
        description="Lists items using one step only",
        steps=[{"alias": "s1", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    result = _tool(mcp, "elliot_list_skills")()
    assert result["count"] == 1


def test_get_skill_returns_definition(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    created = _tool(mcp, "elliot_create_skill")(
        name="get_skill",
        description="A skill to get item counts quickly",
        steps=[{"alias": "s1", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    result = _tool(mcp, "elliot_get_skill")(skill_id=created["skill_id"])
    assert result["name"] == "get_skill"


def test_get_skill_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_skill")(skill_id="ghost")
    assert "error" in result


def test_delete_skill(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    created = _tool(mcp, "elliot_create_skill")(
        name="del_skill",
        description="A skill to be deleted from registry",
        steps=[{"alias": "s1", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    sid = created["skill_id"]
    result = _tool(mcp, "elliot_delete_skill")(skill_id=sid)
    assert result["status"] == "deleted"
    assert session.registry.get_skill(sid) is None


def test_delete_skill_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_delete_skill")(skill_id="ghost")
    assert "error" in result


# ---------------------------------------------------------------------------
# context tools
# ---------------------------------------------------------------------------


def test_set_context_stores_product_context(mcp: FastMCP, session: ElliotSession):
    result = _tool(mcp, "elliot_set_context")(name="Acme", description="Acme Corp API")
    assert result["status"] == "ok"
    assert session.product_context is not None
    assert session.product_context.name == "Acme"


def test_get_context_returns_none_when_unset(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_context")()
    assert result["context"] is None


def test_get_context_after_set(mcp: FastMCP, session: ElliotSession):
    _tool(mcp, "elliot_set_context")(name="TestCo", base_url="https://api.testco.com")
    result = _tool(mcp, "elliot_get_context")()
    assert result["context"]["name"] == "TestCo"


def test_get_session_state_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_session_state")()
    assert result["source_count"] == 0
    assert result["tool_count"] == 0
    assert result["skill_count"] == 0
    assert result["connector_built"] is False


def test_get_session_state_reflects_loaded_data(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_get_session_state")()
    assert result["source_count"] == 1
    assert result["tool_count"] == 1


# ---------------------------------------------------------------------------
# connector tools
# ---------------------------------------------------------------------------


def test_build_connector_returns_built_status(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_build_connector")(
        name="TestConnector", slug="test", version="1.0.0"
    )
    assert result["status"] == "built"
    assert session.connector is not None


def test_export_connector_writes_file(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    _tool(mcp, "elliot_build_connector")(name="MyConnector", slug="my", version="1.0.0")
    export_path = str(tmp_path / "connector.json")
    result = _tool(mcp, "elliot_export_connector")(path=export_path)
    assert result["status"] == "exported"
    assert Path(export_path).exists()
    data = json.loads(Path(export_path).read_text())
    assert data["name"] == "MyConnector"


def test_export_connector_without_build_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_export_connector")(path="/tmp/test.json")
    assert "error" in result


def test_get_connection_config(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_connection_config")()
    assert result["type"] == "http"
    assert "localhost:3001" in result["url"]


def test_stop_runtime_when_not_running(mcp: FastMCP):
    result = _tool(mcp, "elliot_stop_runtime")()
    assert result["status"] == "not_running"
