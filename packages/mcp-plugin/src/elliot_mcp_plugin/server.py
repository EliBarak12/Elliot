from __future__ import annotations

from typing import Any

import mcp.types as types
import structlog
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

from elliot_core.connector.schema_gen import to_mcp_tool_schema
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig

log = structlog.get_logger(__name__)


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
        except Exception as exc:
            # CLAUDE.md: every MCP tool handler has a top-level catch-all.
            # A non-ElliotError (bug, network failure) must not escape and
            # crash the stdio process — log the trace, return a safe error.
            log.error("call_tool.unhandled", tool=name, exc_info=exc)
            content = to_mcp_error_content(exc)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=content["text"])],
                isError=True,
            )

    return server


def _local_instructions() -> str:
    """Server instructions for the locally-installed Elliot plugin.

    Skills are delivered by the agent's plugin loader (Claude Code / Codex
    auto-discover the SKILL.md files under ``skills/``), not as MCP prompts —
    so this text points at the plugin-loaded ``getting-started`` skill rather
    than ``prompts/get``. The hosted Elliot Cloud builder swaps in its own
    instructions (and serves the skills as MCP prompts) in the cloud layer."""
    return (
        "Elliot turns any API or database into agent-ready MCP tools. You are the "
        "agent that designs, lints, evaluates, and deploys those tools — Elliot is "
        "the workbench.\n"
        "\n"
        "Your harness loads Elliot's skills from the installed plugin (Claude Code "
        "and Codex auto-discover them under `skills/`). Consult the `getting-started` "
        "skill first: it teaches the five principles, the canonical workflow, AND "
        "what to do when an Elliot tool call fails with a connection error (the "
        "usual cause is the user hasn't started the Elliot stack yet).\n"
        "\n"
        "If a later Elliot tool call hits a transport / connection-refused error, "
        "STOP retrying and re-read the `getting-started` skill. The recovery path is "
        "to ask the user to run `make dev` from a clone of EliBarak12/Elliot — "
        "Studio (http://localhost:5173) opens automatically in their browser when "
        "the stack is up.\n"
        "\n"
        "Available resources (call `resources/list`): connector templates "
        "(rest-api-key, postgres-readonly, paginated-rest, openapi-petstore), "
        "principles, error-code reference, install docs."
    )


def create_elliot_server(session: Any) -> FastMCP:
    """Create a FastMCP server with all Elliot tool groups and resources registered.

    Skills are NOT registered as MCP prompts here: locally the agent's plugin
    loader delivers them as SKILL.md files. The hosted Elliot Cloud builder
    registers them as prompts (and overrides the instructions / install doc)
    post-build in its own layer — see the cloud runtime.
    """
    from elliot_mcp_plugin.resources import register_resources
    from elliot_mcp_plugin.tools.audit_tools import register_audit_tools
    from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
    from elliot_mcp_plugin.tools.context_tools import register_context_tools
    from elliot_mcp_plugin.tools.eval_tools import register_eval_tools
    from elliot_mcp_plugin.tools.onboarding_tools import register_onboarding_tools
    from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
    from elliot_mcp_plugin.tools.source_tools import register_source_tools
    from elliot_mcp_plugin.tools.sql_tools import register_sql_tools
    from elliot_mcp_plugin.tools.studio_tools import register_studio_tools
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools
    from elliot_mcp_plugin.tools.trace_tools import register_trace_tools

    mcp = FastMCP(
        "elliot",
        instructions=_local_instructions(),
        streamable_http_path="/",
        stateless_http=True,
    )
    register_source_tools(mcp, session)
    register_sql_tools(mcp, session)
    register_tool_tools(mcp, session)
    register_skill_tools(mcp, session)
    register_context_tools(mcp, session)
    register_connector_tools(mcp, session)
    register_studio_tools(mcp, session)
    register_eval_tools(mcp, session)
    register_onboarding_tools(mcp, session)
    register_audit_tools(mcp, session)
    register_trace_tools(mcp, session)
    register_resources(mcp)
    _hide_destructive_tools_from_other_agents(mcp)
    return mcp


_STUDIO_CLIENT_NAME = "elliot-studio"

# Tools that are visible only to the Studio UI / Cloud dashboard, never to
# coding agents. Read-only Studio panels (logs, metrics, connector info, raw
# SELECT) are intentionally NOT in this list — agents benefit from seeing
# their own session, audit trail, and being able to validate tools. The
# denylist is strictly destructive actions that should be human-confirmed.
_DESTRUCTIVE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "studio_remove_source",
        # Log-wiping / harness-config changes are human-confirmed actions,
        # triggered from Studio or Cloud — not reachable by arbitrary connected
        # MCP clients. (Studio's own client identity still sees them.)
        # elliot_delete_tool / elliot_delete_skill are deliberately NOT here:
        # hiding them while elliot_delete_source (which cascade-deletes tools!)
        # stayed visible was backwards — an agent that can drop a whole source
        # must be able to prune one tool or skill. Both are design-time edits
        # to the draft, not runtime-destructive actions.
        "elliot_clear_audit_transcripts",
        "elliot_uninstall_trace_hook",
    }
)


def _format_validation_error(exc: Any) -> str:
    """Turn a pydantic ValidationError (raised by FastMCP's argument validation,
    before our handlers' try/except can run) into the same ``[CODE] message``
    envelope our ElliotError path uses, so agents can branch on the code rather
    than parse a raw pydantic dump."""
    try:
        errors = exc.errors()
    except Exception:
        return "[VALIDATION_ERROR] Invalid arguments."
    if not errors:
        return "[VALIDATION_ERROR] Invalid arguments."
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ())) or "argument"
    if first.get("type") == "missing":
        return f"[VALIDATION_MISSING_FIELD] Missing required field: {loc}"
    return f"[VALIDATION_TYPE] Invalid value for '{loc}': {first.get('msg', 'type error')}"


def _is_studio_client() -> bool:
    """Return True iff the current request's agent identity is Studio's.

    Identity is bound to a contextvar by ``AgentIdentityMiddleware`` for HTTP
    requests; stdio sessions have no header and therefore no identity, which
    we treat as "not Studio" so destructive tools stay hidden from CLI use.
    """
    from elliot_core.agent_identity import get_current_agent_identity

    identity = get_current_agent_identity()
    if identity is None or not identity.client:
        return False
    return identity.client.lower() == _STUDIO_CLIENT_NAME


def _hide_destructive_tools_from_other_agents(mcp: FastMCP) -> None:
    """Filter destructive tools out of ``tools/list`` and ``call_tool`` for
    non-Studio agents.

    Read-only Studio diagnostics (``studio_get_connector_info``,
    ``studio_get_audit_log``, ``studio_get_metrics``, ``studio_run_sql``)
    are deliberately visible to agents — they get their own session state,
    audit trail, and aggregated metrics to reason about quality. Only
    destructive actions (currently ``studio_remove_source``) are hidden, so
    source/tool deletion must be triggered by a human in Studio or Cloud.
    """
    tool_manager = mcp._tool_manager
    original_list = tool_manager.list_tools
    original_call = tool_manager.call_tool

    def filtered_list() -> Any:
        tools = original_list()
        if _is_studio_client():
            return tools
        return [t for t in tools if t.name not in _DESTRUCTIVE_TOOL_NAMES]

    async def filtered_call(
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
        convert_result: bool = False,
    ) -> Any:
        if name in _DESTRUCTIVE_TOOL_NAMES and not _is_studio_client():
            raise ElliotError(
                "TOOL_NOT_FOUND",
                f"Unknown tool: {name}",
            )
        from mcp.server.fastmcp.exceptions import ToolError
        from pydantic import ValidationError as PydanticValidationError

        try:
            return await original_call(name, arguments, context, convert_result)
        except ToolError as exc:
            # FastMCP's Tool.run wraps every in-handler exception — including the
            # pydantic argument-validation error that fires BEFORE a handler's
            # own try/except — as ToolError(__cause__=original). Re-surface the
            # cause as the structured "[CODE] message" envelope so agents can
            # branch on VALIDATION_*/Elliot codes instead of a raw pydantic dump.
            cause = exc.__cause__
            if isinstance(cause, ElliotError):
                raise ToolError(f"[{cause.code}] {cause.message}") from cause
            if isinstance(cause, PydanticValidationError):
                raise ToolError(_format_validation_error(cause)) from cause
            raise

    tool_manager.list_tools = filtered_list  # type: ignore[method-assign]
    tool_manager.call_tool = filtered_call  # type: ignore[method-assign]


async def run_stdio(config: ConnectorConfig, secrets: dict[str, str]) -> None:
    server = create_server(config, secrets)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
