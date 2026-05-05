from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server import Server
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


async def run_stdio(config: ConnectorConfig, secrets: dict[str, str]) -> None:
    server = create_server(config, secrets)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
