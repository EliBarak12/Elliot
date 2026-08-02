"""Thin wrapper around the MCP client used by Layer 1 tests.

The real Studio UI talks to the plugin through the exact same transport
(``StreamableHTTPClientTransport`` in ``packages/studio/src/lib/mcp-client.ts``),
so by speaking the same protocol from Python we're testing the wire-level
contract a real client sees — not the in-process function calls the
existing integration tests exercise.

SDK v2 note: the high-level ``mcp.client.Client`` replaces the old
``streamablehttp_client`` + ``ClientSession`` pair. ``mode`` selects the
protocol era — ``"legacy"`` forces the 2025 initialize handshake,
``"auto"`` (default) probes ``server/discover`` and speaks 2026-07-28
stateless when the server supports it — so Layer 1 can exercise both paths
against the same running stack.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def open_mcp_session(
    mcp_url: str,
    *,
    headers: Mapping[str, str] | None = None,
    mode: Literal["legacy", "auto"] = "auto",
) -> AsyncIterator[Client]:
    """Open an MCP connection over streamable HTTP and yield a ready ``Client``."""
    if headers:
        # Custom headers ride on a pre-configured httpx2 client (the v2 SDK
        # dropped the old headers= kwarg). Client() enters the un-entered
        # transport context manager itself.
        http_client = httpx2.AsyncClient(headers=dict(headers))
        transport = streamable_http_client(mcp_url, http_client=http_client)
        async with http_client, Client(transport, mode=mode) as client:
            yield client
    else:
        async with Client(mcp_url, mode=mode) as client:
            yield client


async def call_tool_json(
    client: Client, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call an MCP tool and return the parsed JSON body as a dict.

    The server serializes Python ``dict`` returns as a single JSON
    ``TextContent`` block — ``structured_content`` is not populated for plain
    dict returns — so we parse the text ourselves. On ``is_error=True`` this
    raises an ``AssertionError`` so test code can ``await`` linearly without
    branching.
    """
    result = await client.call_tool(name, arguments or {})

    body_text: str | None = None
    if result.content:
        first = result.content[0]
        body_text = getattr(first, "text", None)

    if result.is_error:
        raise AssertionError(f"MCP tool {name!r} failed: {body_text or '<no body>'}")

    if result.structured_content is not None:
        return dict(result.structured_content)
    if body_text is None:
        return {}
    try:
        return json.loads(body_text)
    except json.JSONDecodeError:
        return {"text": body_text}
