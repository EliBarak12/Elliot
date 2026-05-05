"""Tests for create_elliot_server: factory returns a configured FastMCP instance."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


def test_create_elliot_server_returns_fastmcp(session: ElliotSession):
    server = create_elliot_server(session)
    assert isinstance(server, FastMCP)


def test_create_elliot_server_registers_tools(session: ElliotSession):
    server = create_elliot_server(session)
    # FastMCP stores tools in _tool_manager
    tool_names = list(server._tool_manager._tools.keys())
    assert len(tool_names) > 0


def test_all_tool_groups_registered(session: ElliotSession):
    server = create_elliot_server(session)
    tool_names = list(server._tool_manager._tools.keys())
    expected_prefixes = {
        "elliot_discover_source",  # source_tools
        "elliot_query_sql",  # sql_tools
        "elliot_list_tools",  # tool_tools
        "elliot_list_skills",  # skill_tools
        "elliot_set_context",  # context_tools
        "elliot_build_connector",  # connector_tools
        "elliot_session_summary",  # studio_tools
    }
    for expected in expected_prefixes:
        assert expected in tool_names, f"Missing tool: {expected}"


def test_create_multiple_servers_independent(session: ElliotSession, tmp_path: Path):
    session2 = ElliotSession(cwd=str(tmp_path / "s2"))
    s1 = create_elliot_server(session)
    s2 = create_elliot_server(session2)
    assert s1 is not s2
