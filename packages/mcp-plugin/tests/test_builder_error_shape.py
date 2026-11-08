"""Builder tools fail one way: isError, with ``[CODE] message``.

Before, a refused call came back as a success in one of three shapes — a
content block JSON-encoded inside a content block, ``{"error": "..."}``, or
``{"status": "blocked"}`` — so an agent had to parse text to learn it had
failed.
"""

from __future__ import annotations

from pathlib import Path

from mcp.client import Client

from elliot_core.types.source import SourceConfig
from elliot_mcp_plugin.server import _as_error_when_refused, create_elliot_server
from elliot_mcp_plugin.session import ElliotSession


async def test_refusals_arrive_as_errors_with_a_code(tmp_path: Path) -> None:
    session = ElliotSession(cwd=str(tmp_path))
    mcp = create_elliot_server(session)
    async with Client(mcp, mode="legacy") as client:  # type: ignore[arg-type]
        missing = await client.call_tool("elliot_preview_tool", {"tool_id": "nope"})
        text = missing.content[0].text
        assert missing.is_error and text.endswith("[NOT_FOUND] Tool not found: nope"), text

        refused = await client.call_tool(
            "elliot_create_rest_tool",
            {
                "name": "search_users",
                "description": "Search users by name",
                "source_id": "users",
                "query_params": [],
            },
        )
        text = refused.content[0].text
        assert refused.is_error and "Source not found: users" in text, text


async def test_a_source_is_found_by_its_name_or_its_id(tmp_path: Path) -> None:
    session = ElliotSession(cwd=str(tmp_path))
    session.sources["08fa8968"] = SourceConfig.model_validate(
        {"id": "08fa8968", "type": "rest", "name": "users", "url": "https://api.example.com/users"}
    )
    mcp = create_elliot_server(session)
    async with Client(mcp, mode="legacy") as client:  # type: ignore[arg-type]
        made = await client.call_tool(
            "elliot_create_rest_tool",
            {
                "name": "search_users",
                "description": "Search users by name; returns matching users.",
                "source_id": "users",
                "query_params": [
                    {"name": "q", "type": "string", "required": False, "description": "Name"}
                ],
            },
        )
        assert not made.is_error, made.content[0].text
        miss = await client.call_tool(
            "elliot_create_rest_tool",
            {
                "name": "x_tool",
                "description": "Search things by name",
                "source_id": "people",
                "query_params": [
                    {"name": "q", "type": "string", "required": False, "description": "Name"}
                ],
            },
        )
        text = miss.content[0].text
        assert miss.is_error and "users (id 08fa8968, rest)" in text and "name or its id" in text


def test_blocked_gate_keeps_its_detail_but_is_an_error() -> None:
    import mcp.types as types

    blocked = types.CallToolResult(
        content=[types.TextContent(type="text", text="{}")],
        structured_content={"status": "blocked", "reason": "lint_errors", "issues": [{"x": 1}]},
    )
    out = _as_error_when_refused(blocked)
    assert out.is_error and out.structured_content["issues"] == [{"x": 1}]
    assert '"reason":"lint_errors"' in out.content[0].text
    fine = types.CallToolResult(content=[], structured_content={"status": "created"})
    assert _as_error_when_refused(fine) is fine
    text_only = types.CallToolResult(
        content=[types.TextContent(type="text", text='{"status": "blocked"}')]
    )
    assert _as_error_when_refused(text_only).is_error
    import pytest

    from elliot_core.mcp_compat import ToolError

    nested = types.CallToolResult(
        content=[], structured_content={"error": {"code": "TOO_BIG", "message": "Max 10 MB."}}
    )
    with pytest.raises(ToolError, match=r"^\[TOO_BIG\] Max 10 MB\.$"):
        _as_error_when_refused(nested)
    not_json = types.CallToolResult(content=[types.TextContent(type="text", text="{oops")])
    assert _as_error_when_refused(not_json) is not_json
    assert _as_error_when_refused("not a result") == "not a result"
