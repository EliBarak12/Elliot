"""End-user identity for per-user connector auth (auth boundary 1).

This is distinct from ``agent_identity`` (which captures *which AI tool/model*
is calling). Here we track *which end user* the request is on behalf of, so the
runtime can resolve that user's own upstream credential from the per-user vault.

In a full remote deployment the user id is the ``sub`` claim of a validated
OAuth token. For gateway/self-hosted setups it is carried in a signed
``X-Elliot-User`` header. For local stdio/dev there is a single ``local`` user.
"""

from __future__ import annotations

import contextvars

# Header a fronting gateway (or the MCP client config) sets to identify the
# end user. Production deployments should derive this from a validated token
# rather than trusting a raw header from the public internet.
USER_HEADER = "x-elliot-user"
LOCAL_USER = "local"

_user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "elliot_user_id", default=None
)


def set_current_user_id(user_id: str | None) -> contextvars.Token[str | None]:
    """Bind the current end-user id; returns a token for later reset."""
    return _user_id_var.set(user_id)


def reset_current_user_id(token: contextvars.Token[str | None]) -> None:
    """Restore the previous end-user id binding."""
    _user_id_var.reset(token)


def get_current_user_id() -> str | None:
    """Return the end-user id bound to this request, or None if unauthenticated."""
    return _user_id_var.get()


def parse_user_id(headers: dict[str, str]) -> str | None:
    """Extract the end-user id from request headers (case-insensitive)."""
    value = headers.get(USER_HEADER) or headers.get(USER_HEADER.title())
    if value:
        value = value.strip()
    return value or None


__all__ = [
    "LOCAL_USER",
    "USER_HEADER",
    "get_current_user_id",
    "parse_user_id",
    "reset_current_user_id",
    "set_current_user_id",
]
