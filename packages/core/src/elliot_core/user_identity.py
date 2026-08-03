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
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class UserScope:
    """Row-level access scope for managed ("elliot") sources.

    The hosting layer (Elliot Cloud's runtime forwarder, a self-hosted
    gateway) resolves sharing grants into this scope per request:

    * ``readable_owner_ids`` — owners *beyond the user themself* whose rows
      this user may read (they granted the user access).
    * ``writable_owner_ids`` — owners beyond the user whose rows this user
      may update/delete (a read+write grant).

    The user always reads and writes their own rows; these lists only add to
    that. When no scope is bound the managed store falls back to the plain
    user id (single-owner scoping), and with no identity at all it runs
    unscoped — the local single-user mode.
    """

    user_id: str
    email: str | None = None
    readable_owner_ids: tuple[str, ...] = field(default_factory=tuple)
    writable_owner_ids: tuple[str, ...] = field(default_factory=tuple)


_user_scope_var: contextvars.ContextVar[UserScope | None] = contextvars.ContextVar(
    "elliot_user_scope", default=None
)


def set_current_user_scope(scope: UserScope | None) -> contextvars.Token[UserScope | None]:
    """Bind the current user's managed-data scope; returns a token for reset."""
    return _user_scope_var.set(scope)


def reset_current_user_scope(token: contextvars.Token[UserScope | None]) -> None:
    """Restore the previous user-scope binding."""
    _user_scope_var.reset(token)


def get_current_user_scope() -> UserScope | None:
    """Return the managed-data scope bound to this request, if any."""
    return _user_scope_var.get()


def managed_owner_id() -> str:
    """The owner id stamped onto rows the current caller inserts."""
    scope = get_current_user_scope()
    if scope is not None:
        return scope.user_id
    return get_current_user_id() or LOCAL_USER


def managed_read_owner_ids() -> list[str] | None:
    """Owner ids whose rows the current caller may READ, or None for unscoped.

    None (no identity bound at all) means the local single-user mode: no
    row filter is applied. With an identity but no explicit scope, reads are
    limited to the caller's own rows.
    """
    scope = get_current_user_scope()
    if scope is not None:
        return [scope.user_id, *scope.readable_owner_ids]
    user_id = get_current_user_id()
    if user_id is not None:
        return [user_id]
    return None


def managed_write_owner_ids() -> list[str] | None:
    """Owner ids whose rows the current caller may UPDATE/DELETE, or None."""
    scope = get_current_user_scope()
    if scope is not None:
        return [scope.user_id, *scope.writable_owner_ids]
    user_id = get_current_user_id()
    if user_id is not None:
        return [user_id]
    return None


__all__ = [
    "LOCAL_USER",
    "USER_HEADER",
    "UserScope",
    "get_current_user_id",
    "get_current_user_scope",
    "managed_owner_id",
    "managed_read_owner_ids",
    "managed_write_owner_ids",
    "parse_user_id",
    "reset_current_user_id",
    "reset_current_user_scope",
    "set_current_user_id",
    "set_current_user_scope",
]
