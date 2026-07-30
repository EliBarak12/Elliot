"""Tests for create_elliot_server: factory returns a configured FastMCP instance."""

from __future__ import annotations

from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.server import create_elliot_server
from elliot_mcp_plugin.session import ElliotSession


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


def test_create_elliot_server_returns_fastmcp(session: ElliotSession):
    server = create_elliot_server(session)
    assert isinstance(server, FastMCP)


def test_local_instructions_keep_make_dev_recovery(session: ElliotSession):
    server = create_elliot_server(session)
    instructions = server.instructions or ""
    # The local builder guides the user to start the stack themselves.
    assert "make dev" in instructions
    assert "localhost:5173" in instructions


def test_local_server_does_not_register_skill_prompts(session: ElliotSession):
    """Skills are delivered locally by the plugin SKILL.md loader, not as MCP
    prompts — those are a cloud-only channel registered in the cloud layer."""
    server = create_elliot_server(session)
    assert server._prompt_manager._prompts == {}
    # And the instructions point at the plugin skill, not `prompts/get`.
    assert "prompts/get" not in (server.instructions or "")


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


def test_readonly_studio_tools_visible_to_agents(session: ElliotSession):
    """Read-only Studio diagnostics (logs, metrics, info, run_sql) are visible
    to coding agents so they can inspect their own session and validate tools."""
    server = create_elliot_server(session)
    names = {t.name for t in server._tool_manager.list_tools()}
    assert "elliot_session_summary" in names, "elliot_ tools must stay visible"
    for visible in (
        "studio_get_connector_info",
        "studio_get_audit_log",
        "studio_get_metrics",
        "studio_run_sql",
    ):
        assert visible in names, f"{visible} should be visible to agents"


def test_destructive_tools_hidden_from_unknown_agents(session: ElliotSession):
    """Destructive tools (source/connector removal) never appear in tools/list
    for coding agents — they require a human-pressed button in Studio/Cloud."""
    server = create_elliot_server(session)
    names = {t.name for t in server._tool_manager.list_tools()}
    assert "studio_remove_source" not in names


def test_destructive_tools_visible_to_studio_client(session: ElliotSession):
    """studio_remove_source is visible only when the agent identity is 'elliot-studio'
    (i.e., the local Studio UI's MCP client)."""
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
    assert "studio_remove_source" in names


def test_destructive_tool_call_blocked_for_unknown_agents(session: ElliotSession):
    """Calling a destructive tool as a non-Studio agent must fail like an unknown tool."""
    import asyncio

    from elliot_core.errors import ElliotError

    server = create_elliot_server(session)
    with pytest.raises(ElliotError) as ei:
        asyncio.run(server._tool_manager.call_tool("studio_remove_source", {"source_id": "x"}))
    assert ei.value.code == "TOOL_NOT_FOUND"


def test_newly_hidden_destructive_tools_not_listed(session: ElliotSession):
    """elliot_delete_tool / _delete_skill / clear_audit / uninstall_trace_hook are
    destructive and must be hidden from non-Studio agents (F-020)."""
    server = create_elliot_server(session)
    names = {t.name for t in server._tool_manager.list_tools()}
    for hidden in (
        "elliot_delete_tool",
        "elliot_delete_skill",
        "elliot_clear_audit_transcripts",
        "elliot_uninstall_trace_hook",
    ):
        assert hidden not in names, f"{hidden} should be hidden from non-Studio agents"


def test_missing_required_arg_surfaces_validation_code(session: ElliotSession):
    """Pydantic arg-validation errors are reformatted to the [VALIDATION_*] envelope
    so agents can branch on the code instead of parsing a raw pydantic dump (F-006)."""
    import asyncio

    from elliot_core.mcp_compat import ToolError

    server = create_elliot_server(session)
    with pytest.raises(ToolError) as ei:
        # elliot_query_sql requires `sql`
        asyncio.run(server._tool_manager.call_tool("elliot_query_sql", {}))
    assert "VALIDATION_MISSING_FIELD" in str(ei.value)


class TestEmbedderKnobs:
    """The keyword knobs Elliot Cloud uses instead of poking SDK privates."""

    def test_instructions_override(self, session) -> None:  # type: ignore[no-untyped-def]
        from elliot_mcp_plugin.server import create_elliot_server

        mcp = create_elliot_server(session, instructions="Cloud builder instructions.")
        assert mcp.instructions == "Cloud builder instructions."

    def test_hide_tools_removes_from_registry(self, session) -> None:  # type: ignore[no-untyped-def]
        from elliot_mcp_plugin.server import create_elliot_server

        mcp = create_elliot_server(session, hide_tools=["elliot_start_runtime"])
        names = {t.name for t in mcp._tool_manager.list_tools()}
        assert "elliot_start_runtime" not in names
        assert "elliot_list_tools" in names

    def test_register_skill_prompts_serves_prompts(self, session) -> None:  # type: ignore[no-untyped-def]
        from elliot_mcp_plugin.server import create_elliot_server

        mcp = create_elliot_server(session, register_skill_prompts=True)
        assert len(mcp._prompt_manager._prompts) > 0

    def test_resource_override_swaps_text(self, session) -> None:  # type: ignore[no-untyped-def]
        import asyncio

        from elliot_mcp_plugin.server import create_elliot_server

        mcp = create_elliot_server(
            session, resource_overrides={"elliot://docs/install": "CLOUD INSTALL DOC"}
        )
        contents = asyncio.run(mcp.read_resource("elliot://docs/install"))
        assert list(contents)[0].content == "CLOUD INSTALL DOC"
