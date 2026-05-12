from __future__ import annotations

from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

from elliot_core.connector.schema_gen import to_mcp_tool_schema
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig


def _make_annotations(schema: dict[str, Any]) -> types.ToolAnnotations:
    ann = schema.get("annotations", {})
    return types.ToolAnnotations(
        title=ann.get("title"),
        readOnlyHint=ann.get("readOnlyHint"),
        destructiveHint=ann.get("destructiveHint"),
        idempotentHint=ann.get("idempotentHint"),
        openWorldHint=ann.get("openWorldHint"),
    )


def build_tool_list(config: ConnectorConfig) -> list[types.Tool]:
    """Pure function: ConnectorConfig -> list of MCP Tool objects."""
    tools = []
    for t in config.tools:
        schema = to_mcp_tool_schema(t)
        tools.append(
            types.Tool(
                name=schema["name"],
                description=schema["description"],
                inputSchema=schema["inputSchema"],
                annotations=_make_annotations(schema),
                outputSchema=schema.get("outputSchema"),
            )
        )
    return tools


def create_server(config: ConnectorConfig, secrets: dict[str, str]) -> Server:
    server = Server("elliot")
    executor = ToolExecutor(config, secrets)
    tools = build_tool_list(config)

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            result = await executor.execute(name, arguments or {})
            structured = {"rows": result.rows, "count": len(result.rows)}
            summary = f"{len(result.rows)} row(s) returned"
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=summary)],
                structuredContent=structured,
                isError=False,
            )
        except ElliotError as exc:
            content = to_mcp_error_content(exc)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=content["text"])],
                isError=True,
            )

    return server


def create_elliot_server(session: Any) -> FastMCP:
    """Create a FastMCP server with all Elliot tool groups registered."""
    from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
    from elliot_mcp_plugin.tools.context_tools import register_context_tools
    from elliot_mcp_plugin.tools.eval_tools import register_eval_tools
    from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
    from elliot_mcp_plugin.tools.source_tools import register_source_tools
    from elliot_mcp_plugin.tools.sql_tools import register_sql_tools
    from elliot_mcp_plugin.tools.studio_tools import register_studio_tools
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    instructions = (
        "Elliot helps you build agent-ready MCP connectors from any API or database. "
        "Start with elliot_set_context to name your connector, then elliot_discover_source "
        "to describe your data source. Use elliot_create_tool to define agent-callable tools "
        "with verb-first descriptions. Run elliot_lint_connector before saving. "
        "Use elliot_run_eval to validate tool quality against expected outputs."
    )
    mcp = FastMCP(
        "elliot", instructions=instructions, streamable_http_path="/", stateless_http=True
    )
    register_source_tools(mcp, session)
    register_sql_tools(mcp, session)
    register_tool_tools(mcp, session)
    register_skill_tools(mcp, session)
    register_context_tools(mcp, session)
    register_connector_tools(mcp, session)
    register_studio_tools(mcp, session)
    register_eval_tools(mcp, session)
    return mcp


async def run_stdio(config: ConnectorConfig, secrets: dict[str, str]) -> None:
    server = create_server(config, secrets)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
