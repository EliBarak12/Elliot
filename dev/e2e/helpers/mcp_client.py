"""Thin wrapper around the MCP streamable-HTTP client used by Layer 1 tests.

The real Studio UI talks to the plugin through the exact same transport
(``StreamableHTTPClientTransport`` in ``packages/studio/src/lib/mcp-client.ts``),
so by speaking the same protocol from Python we're testing the wire-level
contract a real client sees — not the in-process function calls the
existing integration tests exercise.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@asynccontextmanager
async def open_mcp_session(mcp_url: str) -> AsyncIterator[ClientSession]:
    """Open an MCP session over streamable HTTP and yield a ready ``ClientSession``."""
    async with (
        streamablehttp_client(mcp_url) as (read, write, _get_session_id),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def call_tool_json(
    session: ClientSession, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call an MCP tool and return the parsed JSON body as a dict.

    FastMCP serializes Python ``dict`` returns as a single JSON ``TextContent``
    block — ``structuredContent`` is not populated for plain dict returns —
    so we parse the text ourselves. On ``isError=True`` this raises an
    ``AssertionError`` so test code can ``await`` linearly without branching.
    """
    result = await session.call_tool(name, arguments or {})

    body_text: str | None = None
    if result.content:
        first = result.content[0]
        body_text = getattr(first, "text", None)

    if result.isError:
        raise AssertionError(f"MCP tool {name!r} failed: {body_text or '<no body>'}")

    if result.structuredContent is not None:
        return dict(result.structuredContent)
    if body_text is None:
        return {}
    try:
        return json.loads(body_text)
    except json.JSONDecodeError:
        return {"text": body_text}
