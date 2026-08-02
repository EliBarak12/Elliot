"""Elliot session handles — application-level sessions on a stateless wire.

The 2026-07-28 MCP revision removed protocol sessions (the ``Mcp-Session-Id``
header is gone; every request may hit any replica). The spec's guidance for
servers that need continuity is explicit, server-minted handles — this module
is that: Elliot mints an ``es_<hex>`` handle on the first request of a
journey, echoes it on every response (``Elliot-Session-Id`` header and result
``_meta["io.elliot/session"]``), and accepts it back from cooperating clients.
Non-cooperating clients still get best-effort journeys via
``session_tracker.stitch_stateless_fragments``.

Resolution priority for an inbound request:
``Elliot-Session-Id`` header → request ``_meta`` (upgraded later at the MCP
tier) → legacy ``Mcp-Session-Id`` (2025-era transports) → mint.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

SESSION_META_KEY = "io.elliot/session"
SESSION_HEADER = "Elliot-Session-Id"

HandleSource = Literal["header", "meta", "legacy", "minted"]

# Client-supplied correlation ids are accepted as-is when they look like an
# id (so harnesses can bring their own), but never anything that couldn't
# safely round-trip in a header or a filename-ish log field.
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_MINTED_RE = re.compile(r"^es_[0-9a-f]{12}$")


@dataclass(frozen=True)
class SessionHandle:
    """A resolved session handle plus where it came from."""

    value: str
    source: HandleSource


def mint_session_handle() -> str:
    """Mint a fresh server-side session handle (``es_`` + 12 hex chars)."""
    return f"es_{uuid.uuid4().hex[:12]}"


def is_minted_handle(value: str) -> bool:
    """True iff ``value`` has the shape of an Elliot-minted handle."""
    return bool(_MINTED_RE.match(value))


def _acceptable_client_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if _CLIENT_ID_RE.match(candidate):
        return candidate
    return None


def resolve_inbound(headers: Mapping[str, str]) -> SessionHandle:
    """Resolve the session handle for an inbound HTTP request.

    ``headers`` must be lower-cased keys (the ASGI middleware provides that).
    A malformed client value is ignored rather than erroring — a bad
    correlation id must never break a tool call — and a fresh handle is
    minted instead.
    """
    explicit = _acceptable_client_id(headers.get(SESSION_HEADER.lower()))
    if explicit is not None:
        return SessionHandle(explicit, "header")
    legacy = _acceptable_client_id(headers.get("mcp-session-id"))
    if legacy is not None:
        return SessionHandle(legacy, "legacy")
    return SessionHandle(mint_session_handle(), "minted")


class _HandleBox:
    """Mutable holder so an upgrade made in a child task context (the MCP
    dispatch runs handlers in task-group children) stays visible to the ASGI
    middleware that bound the box — a plain ``ContextVar.set`` in a child
    context would never propagate back to the response-header echo."""

    __slots__ = ("handle",)

    def __init__(self, handle: SessionHandle) -> None:
        self.handle = handle


_current_handle: ContextVar[_HandleBox | None] = ContextVar("elliot_session_handle", default=None)


def get_current_session_handle() -> SessionHandle | None:
    """The request's resolved session handle, or ``None`` outside a request."""
    box = _current_handle.get()
    return box.handle if box is not None else None


def set_current_session_handle(handle: SessionHandle) -> Token[_HandleBox | None]:
    return _current_handle.set(_HandleBox(handle))


def reset_current_session_handle(token: Token[_HandleBox | None]) -> None:
    _current_handle.reset(token)


def upgrade_from_meta(meta_value: object) -> SessionHandle | None:
    """Adopt a handle carried in request ``_meta`` when it outranks the current one.

    The header always wins (it was the client's most explicit statement); a
    ``_meta`` handle upgrades over ``legacy``/``minted`` resolutions. Returns
    the new current handle when an upgrade happened, else ``None``.
    """
    if not isinstance(meta_value, str):
        return None
    candidate = _acceptable_client_id(meta_value)
    if candidate is None:
        return None
    box = _current_handle.get()
    current = box.handle if box is not None else None
    if current is not None and current.source == "header":
        return None
    if current is not None and current.value == candidate:
        return None
    handle = SessionHandle(candidate, "meta")
    if box is not None:
        # Mutate in place so the ASGI-tier echo sees the upgrade.
        box.handle = handle
    else:
        _current_handle.set(_HandleBox(handle))
    return handle
