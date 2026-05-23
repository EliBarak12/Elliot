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


def test_studio_tools_hidden_from_unknown_agents(session: ElliotSession):
    """studio_* tools must not appear in tools/list for non-Studio agents."""
    server = create_elliot_server(session)
    names = {t.name for t in server._tool_manager.list_tools()}
    assert "elliot_session_summary" in names, "elliot_ tools must stay visible"
    for hidden in (
        "studio_get_connector_info",
        "studio_get_audit_log",
        "studio_get_metrics",
        "studio_run_sql",
    ):
        assert hidden not in names, f"{hidden} leaked into tools/list for unknown agent"


def test_studio_tools_visible_to_studio_client(session: ElliotSession):
    """studio_* tools are visible when the agent identity is 'elliot-studio'."""
    from elliot_core.agent_identity import (
        AgentIdentity,
        reset_current_agent_identity,
        set_current_agent_identity,
    )

    server = create_elliot_server(session)
    token = set_current_agent_identity(AgentIdentity(client="elliot-studio"))
    try:
        names = {t.name for t in server._tool_manager.list_tools()}
    finally:
        reset_current_agent_identity(token)
    for visible in (
        "studio_get_connector_info",
        "studio_get_audit_log",
        "studio_get_metrics",
        "studio_run_sql",
    ):
        assert visible in names, f"{visible} hidden from Studio"


def test_studio_tool_call_blocked_for_unknown_agents(session: ElliotSession):
    """Calling a studio_* tool as a non-Studio agent must fail like an unknown tool."""
    import asyncio

    from elliot_core.errors import ElliotError

    server = create_elliot_server(session)
    with pytest.raises(ElliotError) as ei:
        asyncio.run(server._tool_manager.call_tool("studio_get_audit_log", {}))
    assert ei.value.code == "TOOL_NOT_FOUND"
