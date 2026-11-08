"""The verified caller's credentials, for calls made on that caller's behalf.

A connector served behind its owner's own sign-in (Elliot Cloud's
``external_oauth`` mode) acts for each signed-in user. The hosting layer
verifies the user's token, works out what the upstream API should receive,
and binds it here for the duration of one request. A source names what it
needs with ``{{ caller:NAME }}`` placeholders:

* ``{{ caller:token }}`` — an access token for the upstream API, minted for
  this caller (by OAuth token exchange). Never the token the caller presented
  to the connector: MCP forbids passing that through.
* ``{{ caller:sub }}`` — the caller's stable user id at the owner's identity
  provider, e.g. in a header the API trusts alongside the connector's
  service key.
* ``{{ caller:email }}`` — the caller's email, when the token carries one.

Values live only in a context variable, so one caller's credential can never
reach another caller's request. A source that uses them is fetched live on
every call and never cached in the runtime's shared snapshot.
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING

from elliot_core.errors import ElliotError

if TYPE_CHECKING:
    from elliot_core.types import SourceConfig

CALLER_FIELDS = ("token", "sub", "email")
_PLACEHOLDER = re.compile(r"^\{\{\s*caller:([a-z_]+)\s*\}\}$")
_ANY_PLACEHOLDER = re.compile(r"\{\{\s*caller:[a-z_]+\s*\}\}")

_caller_var: contextvars.ContextVar[Mapping[str, str] | None] = contextvars.ContextVar(
    "elliot_caller_credentials", default=None
)


class CallerCredentialMissingError(ElliotError):
    """A source needs the caller's credential, and none is bound to this call."""

    def __init__(self, name: str, message: str | None = None) -> None:
        super().__init__(
            "AUTH_REQUIRED",
            message
            or (
                f"This tool acts as the signed-in user, but no '{name}' is available for "
                "this call. Sign in to the connector and retry."
            ),
            detail={"caller_field": name},
        )
        self.name = name


def caller_placeholder(value: str) -> str | None:
    """The field a whole-string ``{{ caller:NAME }}`` placeholder names, else None."""
    match = _PLACEHOLDER.match(value.strip())
    return match.group(1) if match else None


def mentions_caller(value: str) -> bool:
    return bool(_ANY_PLACEHOLDER.search(value))


@contextmanager
def caller_credentials(values: Mapping[str, str]) -> Iterator[None]:
    """Bind the caller's values for the code (and tasks it starts) inside the block."""
    token = _caller_var.set({k: v for k, v in values.items() if v})
    try:
        yield
    finally:
        _caller_var.reset(token)


def bound_caller() -> Mapping[str, str] | None:
    return _caller_var.get()


def resolve_caller(name: str) -> str:
    """The bound value for ``name``; raises :class:`CallerCredentialMissingError`."""
    values = _caller_var.get()
    value = values.get(name) if values else None
    if not value:
        raise CallerCredentialMissingError(name)
    return value


def source_uses_caller(source: SourceConfig) -> bool:
    """Whether any credential or header of ``source`` is the caller's."""
    if source.auth is not None and mentions_caller(source.auth.secret_key):
        return True
    return any(mentions_caller(v) for v in (source.headers or {}).values())
