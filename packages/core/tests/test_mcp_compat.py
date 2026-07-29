"""Contract tests for elliot_core.mcp_compat — the single SDK touchpoint.

These tests pin (a) the era-uniform client-identity extraction across the
2025 handshake path and the 2026 stateless path, and (b) the two private SDK
surfaces we still wrap (`_tool_manager.list_tools` / `.call_tool`), so an SDK
bump that moves them fails here loudly instead of misbehaving in production.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from mcp.client import Client
from mcp.types import Implementation

from elliot_core.mcp_compat import (
    CacheHint,
    ClientIdentity,
    Context,
    MCPServer,
    ToolError,
    build_http_app,
    capability_names,
    create_server,
    get_client_identity,
    register_legacy_set_level,
    wrap_tool_calls,
    wrap_tool_listing,
)

CLIENT_INFO = Implementation(name="compat-test-client", version="9.9.9")


def _make_server() -> tuple[MCPServer, dict[str, Any]]:
    """A server with one echo tool that records the identity it observed."""
    seen: dict[str, Any] = {}
    mcp = create_server("compat-probe", instructions="probe")

    @mcp.tool()
    def echo(text: str, ctx: Context) -> str:
        seen["identity"] = get_client_identity(ctx)
        return text

    return mcp, seen


class TestRoundTrips:
    async def test_legacy_handshake_roundtrip(self) -> None:
        mcp, _ = _make_server()
        async with Client(mcp, mode="legacy", client_info=CLIENT_INFO) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert "echo" in names
            result = await client.call_tool("echo", {"text": "hi"})
            assert result.is_error is not True

    async def test_modern_roundtrip(self) -> None:
        mcp, _ = _make_server()
        async with Client(mcp, mode="auto", client_info=CLIENT_INFO) as client:
            result = await client.call_tool("echo", {"text": "hi"})
            assert result.is_error is not True


class TestClientIdentity:
    async def test_identity_on_legacy_path(self) -> None:
        mcp, seen = _make_server()
        async with Client(mcp, mode="legacy", client_info=CLIENT_INFO) as client:
            await client.call_tool("echo", {"text": "x"})
        identity = seen["identity"]
        assert isinstance(identity, ClientIdentity)
        assert identity.client_name == "compat-test-client"
        assert identity.client_version == "9.9.9"
        assert identity.protocol_version is not None

    async def test_identity_on_modern_path(self) -> None:
        mcp, seen = _make_server()
        async with Client(mcp, mode="auto", client_info=CLIENT_INFO) as client:
            await client.call_tool("echo", {"text": "x"})
        identity = seen["identity"]
        assert identity.protocol_version is not None
        assert identity.client_name == "compat-test-client"

    def test_identity_never_raises_on_bare_object(self) -> None:
        identity = get_client_identity(object())
        assert identity == ClientIdentity()

    def test_capability_names_none(self) -> None:
        assert capability_names(None) is None


class TestToolWraps:
    def test_call_tool_contract_is_pinned(self) -> None:
        """The SDK-private ToolManager.call_tool must keep the 4-arg shape our
        wrappers (and Elliot Cloud's) rely on."""
        mcp, _ = _make_server()
        params = list(inspect.signature(mcp._tool_manager.call_tool).parameters)
        for expected in ("name", "arguments", "context", "convert_result"):
            assert expected in params

    async def test_wrap_tool_listing_filters(self) -> None:
        mcp, _ = _make_server()
        wrap_tool_listing(mcp, lambda tools: [t for t in tools if t.name != "echo"])
        async with Client(mcp, mode="legacy", client_info=CLIENT_INFO) as client:
            tools = await client.list_tools()
            assert "echo" not in {t.name for t in tools.tools}

    async def test_wrap_tool_calls_can_block_and_pass_through(self) -> None:
        mcp, _ = _make_server()

        def make_wrapper(original: Any) -> Any:
            async def wrapped(
                name: str,
                arguments: dict[str, Any],
                context: Any = None,
                convert_result: bool = False,
            ) -> Any:
                if name == "echo" and arguments.get("text") == "blocked":
                    raise ToolError("[TOOL_NOT_FOUND] Unknown tool: echo")
                return await original(name, arguments, context, convert_result)

            return wrapped

        wrap_tool_calls(mcp, make_wrapper)
        async with Client(mcp, mode="legacy", client_info=CLIENT_INFO) as client:
            ok = await client.call_tool("echo", {"text": "fine"})
            assert ok.is_error is not True
            blocked = await client.call_tool("echo", {"text": "blocked"})
            assert blocked.is_error is True


class TestLegacyLogging:
    async def test_set_level_is_answered(self) -> None:
        mcp, _ = _make_server()
        levels: list[str] = []
        register_legacy_set_level(mcp, on_level=levels.append)
        async with Client(mcp, mode="legacy", client_info=CLIENT_INFO) as client:
            await client.set_logging_level("debug")
        assert levels == ["debug"]


class TestHttpApp:
    def test_build_http_app_returns_asgi_app(self) -> None:
        mcp, _ = _make_server()
        app = build_http_app(mcp, path="/", stateless=True)
        assert callable(app)


class TestCacheHints:
    async def test_cache_hints_annotate_list_results(self) -> None:
        mcp = create_server(
            "cache-probe",
            cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="private")},
        )

        @mcp.tool()
        def noop() -> str:
            return "ok"

        async with Client(mcp, mode="auto", client_info=CLIENT_INFO) as client:
            result = await client.list_tools()
            assert getattr(result, "ttl_ms", None) == 60_000


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
