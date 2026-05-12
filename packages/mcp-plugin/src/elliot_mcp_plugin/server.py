from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

from elliot_core.connector.schema_gen import to_mcp_tool_schema
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig


def build_tool_list(config: ConnectorConfig) -> list[types.Tool]:
    """Pure function: ConnectorConfig -> list of MCP Tool objects."""
    return [
        types.Tool(
            name=schema["name"],
            description=schema["description"],
            inputSchema=schema["inputSchema"],
        )
        for schema in (to_mcp_tool_schema(t) for t in config.tools)
    ]


def create_server(config: ConnectorConfig, secrets: dict[str, str]) -> Server:
    server = Server("elliot")
    executor = ToolExecutor(config, secrets)
    tools = build_tool_list(config)

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.Content]:
        try:
            result = await executor.execute(name, arguments or {})
            return [types.TextContent(type="text", text=json.dumps(result.rows, default=str))]
        except ElliotError as exc:
            content = to_mcp_error_content(exc)
            return [types.TextContent(type="text", text=content["text"])]

    return server


def create_elliot_server(session: Any) -> FastMCP:
    """Create a FastMCP server with all Elliot tool groups registered."""
    from elliot_mcp_plugin.tools.builder_tools import register_builder_tools
    from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
    from elliot_mcp_plugin.tools.context_tools import register_context_tools
    from elliot_mcp_plugin.tools.eval_tools import register_eval_tools
    from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
    from elliot_mcp_plugin.tools.source_tools import register_source_tools
    from elliot_mcp_plugin.tools.sql_tools import register_sql_tools
    from elliot_mcp_plugin.tools.studio_tools import register_studio_tools
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    mcp = FastMCP("elliot", streamable_http_path="/", stateless_http=True)
    register_source_tools(mcp, session)
    register_sql_tools(mcp, session)
    register_tool_tools(mcp, session)
    register_skill_tools(mcp, session)
    register_context_tools(mcp, session)
    register_connector_tools(mcp, session)
    register_studio_tools(mcp, session)
    register_eval_tools(mcp, session)
    register_builder_tools(mcp)
    return mcp


async def run_stdio(config: ConnectorConfig, secrets: dict[str, str]) -> None:
    server = create_server(config, secrets)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
