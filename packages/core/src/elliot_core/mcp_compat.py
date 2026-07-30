"""Single point of contact with the MCP Python SDK.

Every Elliot package (and Elliot Cloud, which imports this module) talks to
the ``mcp`` SDK through these helpers instead of importing SDK internals
directly. The SDK's v1→v2 migration renamed ``FastMCP`` to ``MCPServer``,
moved transport configuration from the constructor to the app builders, and
replaced the per-connection handshake with per-request ``_meta`` on the
2026-07-28 protocol path — concentrating that surface here makes the next
SDK bump a one-module change and keeps the two places we still wrap private
SDK attributes (`_tool_manager`, `_lowlevel_server`) pinned by tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from mcp import types
from mcp.server.caching import CacheableMethod, CacheHint
from mcp.server.mcpserver import Context, Extension, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp_types import (
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)

if TYPE_CHECKING:
    from starlette.applications import Starlette

log = structlog.get_logger(__name__)

# Transitional alias: Elliot code (and its tests) predates the SDK's
# FastMCP → MCPServer rename. New code should annotate with ``MCPServer``.
FastMCP = MCPServer

__all__ = [
    "CacheHint",
    "CacheableMethod",
    "ClientIdentity",
    "Context",
    "Extension",
    "FastMCP",
    "MCPDeprecationWarning",
    "MCPServer",
    "ToolError",
    "TransportSecuritySettings",
    "apply_tool_annotations",
    "build_http_app",
    "capability_names",
    "create_server",
    "get_client_identity",
    "override_resource_text",
    "register_legacy_set_level",
    "session_meta_middleware",
    "types",
    "wrap_tool_calls",
    "wrap_tool_listing",
]


def create_server(
    name: str,
    *,
    instructions: str | None = None,
    extensions: Sequence[Extension] | None = None,
    cache_hints: Mapping[str, CacheHint] | None = None,
    middleware: Sequence[Any] | None = None,
) -> MCPServer:
    """Construct an ``MCPServer``.

    Extensions (e.g. MCP Apps) are consumed at construction time by the SDK
    and cannot be added later — callers must assemble them before this call.
    ``middleware`` entries are the SDK's ``ServerMiddleware`` callables,
    listed outermost-first.
    """
    return MCPServer(
        name,
        instructions=instructions,
        extensions=extensions,
        cache_hints=cache_hints,  # type: ignore[arg-type]
        middleware=middleware,
    )


def build_http_app(
    mcp: MCPServer,
    *,
    path: str = "/",
    stateless: bool = True,
    json_response: bool = False,
    transport_security: TransportSecuritySettings | None = None,
) -> Starlette:
    """Build the streamable-HTTP ASGI app for a server.

    v2 moved transport options off the server constructor onto this builder.
    ``stateless=True`` serves the 2026-07-28 stateless path and 2025-era
    handshake clients from the same endpoint without minting transport
    sessions — session continuity is Elliot's own concern (session handles),
    never the transport's.

    ``transport_security`` defaults to disabling the SDK's DNS-rebinding Host
    check: Elliot's servers sit behind their own auth (ApiKeyMiddleware) and
    are reached through Docker service names and reverse proxies whose Host
    header is never the SDK's ``127.0.0.1`` allow-list entry — with the check
    on, every such deployment answers 421 Misdirected Request.
    """
    if transport_security is None:
        transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return mcp.streamable_http_app(
        streamable_http_path=path,
        stateless_http=stateless,
        json_response=json_response,
        transport_security=transport_security,
    )


@dataclass(frozen=True)
class ClientIdentity:
    """SDK-derived identity of the calling client, uniform across protocol eras."""

    protocol_version: str | None = None
    client_name: str | None = None
    client_version: str | None = None
    capabilities: tuple[str, ...] | None = None


def capability_names(capabilities: types.ClientCapabilities | None) -> tuple[str, ...] | None:
    """Reduce declared client capabilities to the names present.

    The wire sends a present-but-empty object for each supported capability
    and ``None`` for the rest, so presence of the attribute is the signal.
    """
    if capabilities is None:
        return None
    names = [
        name
        for name in ("roots", "sampling", "elicitation", "experimental")
        if getattr(capabilities, name, None) is not None
    ]
    return tuple(names)


def get_client_identity(ctx: Context | Any) -> ClientIdentity:
    """Extract client identity from a request context on either protocol path.

    2025-era clients establish ``session.client_params`` via the initialize
    handshake; 2026-era clients carry the same facts in per-request ``_meta``
    (the SDK synthesizes ``client_params`` only when both clientInfo and
    capabilities are present, so the raw ``_meta`` map is the fallback).
    Returns an empty identity rather than raising — telemetry must never
    break a tool call.
    """
    protocol_version: str | None = None
    client_name: str | None = None
    client_version: str | None = None
    caps: tuple[str, ...] | None = None
    try:
        protocol_version = ctx.protocol_version
    except Exception:  # noqa: BLE001 - property access depends on transport
        protocol_version = None
    try:
        caps = capability_names(ctx.client_capabilities)
    except Exception:  # noqa: BLE001
        caps = None
    client_params = getattr(getattr(ctx, "session", None), "client_params", None)
    info = getattr(client_params, "client_info", None)
    if info is not None:
        client_name = getattr(info, "name", None)
        client_version = getattr(info, "version", None)
    else:
        meta = getattr(getattr(ctx, "request_context", None), "meta", None)
        if isinstance(meta, Mapping):
            raw_info = meta.get(CLIENT_INFO_META_KEY)
            if isinstance(raw_info, Mapping):
                name = raw_info.get("name")
                version = raw_info.get("version")
                client_name = name if isinstance(name, str) else None
                client_version = version if isinstance(version, str) else None
            if protocol_version is None:
                raw_version = meta.get(PROTOCOL_VERSION_META_KEY)
                protocol_version = raw_version if isinstance(raw_version, str) else None
    return ClientIdentity(
        protocol_version=protocol_version,
        client_name=client_name,
        client_version=client_version,
        capabilities=caps,
    )


def wrap_tool_listing(mcp: MCPServer, filter_fn: Callable[[list[Any]], list[Any]]) -> None:
    """Wrap the tool manager's listing so ``filter_fn`` shapes every listing.

    This (and :func:`wrap_tool_calls`) are the two sanctioned touches of the
    SDK-private ``_tool_manager``; ``tests/test_mcp_compat.py`` pins the
    private surface so an SDK bump fails loudly here instead of silently.
    """
    tool_manager = mcp._tool_manager
    original_list = tool_manager.list_tools

    def filtered_list() -> list[Any]:
        return filter_fn(original_list())

    tool_manager.list_tools = filtered_list  # type: ignore[method-assign]


# The SDK's ToolManager.call_tool contract, pinned by tests: positional
# (name, arguments) plus keyword-capable (context, convert_result).
CallToolFn = Callable[..., Awaitable[Any]]


def wrap_tool_calls(mcp: MCPServer, make_wrapper: Callable[[CallToolFn], CallToolFn]) -> None:
    """Replace the tool manager's ``call_tool`` with ``make_wrapper(original)``.

    The wrapper MUST preserve the 4-argument shape
    ``(name, arguments, context=None, convert_result=False)``.
    """
    tool_manager = mcp._tool_manager
    tool_manager.call_tool = make_wrapper(  # type: ignore[assignment, method-assign]
        tool_manager.call_tool
    )


async def session_meta_middleware(ctx: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
    """SDK-tier middleware carrying Elliot session handles over MCP ``_meta``.

    Inbound: a handle in request ``_meta["io.elliot/session"]`` upgrades the
    contextvar bound by the ASGI ``ElliotSessionMiddleware`` (the header
    always outranks it; see ``session_handle.upgrade_from_meta``). Outbound:
    every request result is stamped with the current handle in its ``_meta``,
    so cooperating clients can echo it on their next stateless request and
    keep an exact journey. Notifications pass through untouched.
    """
    from elliot_core.session_handle import (
        SESSION_META_KEY,
        get_current_session_handle,
        upgrade_from_meta,
    )

    # Middleware runs before params validation, so read the raw wire meta
    # when the typed ctx.meta isn't populated yet (the modern HTTP path).
    meta = getattr(ctx, "meta", None)
    if not isinstance(meta, Mapping):
        params = getattr(ctx, "params", None)
        meta = params.get("_meta") if isinstance(params, Mapping) else None
    if isinstance(meta, Mapping):
        upgrade_from_meta(meta.get(SESSION_META_KEY))
    result = await call_next(ctx)
    handle = get_current_session_handle()
    if handle is not None and result is not None:
        try:
            if isinstance(result, dict):
                # Modern path: the handler chain already produced the wire
                # dict; the SDK's serverInfo stamp merges into _meta after us,
                # so this key survives.
                existing_meta = result.get("_meta")
                merged = dict(existing_meta) if isinstance(existing_meta, Mapping) else {}
                merged[SESSION_META_KEY] = handle.value
                result["_meta"] = merged
            elif hasattr(result, "meta"):
                existing = dict(result.meta or {})
                existing[SESSION_META_KEY] = handle.value
                result.meta = existing
        except Exception:  # noqa: BLE001 - echo must never break a response
            log.debug("session_meta.echo_failed", exc_info=True)
    return result


def apply_tool_annotations(
    mcp: MCPServer, policy: Callable[[str], types.ToolAnnotations | None]
) -> None:
    """Stamp annotations onto registered tools by name.

    ``policy(name)`` returns the annotations for a tool or ``None`` to leave
    it untouched. Used by embedders (Elliot Cloud) that classify the builder
    tools post-registration; touching the private tool registry stays HERE so
    the next SDK bump has one place to fix.
    """
    for tool in mcp._tool_manager.list_tools():
        annotations = policy(tool.name)
        if annotations is not None:
            tool.annotations = annotations


def override_resource_text(mcp: MCPServer, uri: str, text: str) -> None:
    """Replace a registered resource's content by URI, keeping its identity.

    Embedders use this to swap environment-specific docs (e.g. the install
    doc, which points at localhost in the local build). The original entry
    may be a function-backed resource, so the override swaps the registry
    entry for a ``TextResource`` carrying the same name/description. Unknown
    URIs log and no-op rather than raise — config drift must not stop the
    server.
    """
    from mcp.server.mcpserver.resources import TextResource

    registry = mcp._resource_manager._resources
    existing = registry.get(uri)
    if existing is None:
        log.warning("compat.override_resource.unknown", uri=uri)
        return
    registry[uri] = TextResource(
        uri=uri,
        name=existing.name,
        title=getattr(existing, "title", None),
        description=existing.description,
        mime_type=existing.mime_type,
        text=text,
    )


def register_legacy_set_level(
    mcp: MCPServer, on_level: Callable[[str], None] | None = None
) -> None:
    """Answer ``logging/setLevel`` for 2025-era clients.

    v2 dropped the ``set_logging_level`` decorator; registering a handler on
    the lowlevel server is the SDK-sanctioned replacement and is what makes
    the server advertise the ``logging`` capability to handshake clients —
    without it a compliant client (e.g. Claude) is never told it may receive
    Elliot's log notifications. On the 2026 path log delivery is per-request
    ``_meta`` opt-in and the SDK gates it without our involvement.
    """

    async def _set_level(ctx: Any, params: types.SetLevelRequestParams) -> types.EmptyResult:
        if on_level is not None:
            on_level(str(params.level))
        return types.EmptyResult()

    mcp._lowlevel_server.add_request_handler(
        "logging/setLevel", types.SetLevelRequestParams, _set_level
    )
