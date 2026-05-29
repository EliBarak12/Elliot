"""Identifier slugification shared by tool and skill creation.

Tool and skill *ids* must be snake_case (``^[a-z][a-z0-9_]*$``) — the linter,
the quality scorer, and several filesystem-backed paths assume it. Free-text
names like ``"List Users"`` must therefore be slugified to ``"list_users"``
before they become ids, otherwise a space/colon in the id surfaces later as a
cryptic ``[Errno 22]`` on Windows or a lint failure.
"""

from __future__ import annotations

import re

_CAMEL_BOUNDARY_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_IDENT = re.compile(r"[^a-z0-9]+")

_VALID_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


def slugify_identifier(name: str) -> str:
    """Convert a free-text name to a snake_case identifier.

    ``"List Users"`` -> ``"list_users"``, ``"getUserByID"`` -> ``"get_user_by_id"``.
    Returns ``""`` when nothing usable remains (caller decides the fallback).
    The result is not guaranteed to start with a letter (e.g. ``"123 go"`` ->
    ``"123_go"``); use :func:`is_valid_identifier` to check.
    """
    s = _CAMEL_BOUNDARY_1.sub(r"\1_\2", name)
    s = _CAMEL_BOUNDARY_2.sub(r"\1_\2", s)
    return _NON_IDENT.sub("_", s.lower()).strip("_")


def is_valid_identifier(candidate: str) -> bool:
    """True iff ``candidate`` matches ``^[a-z][a-z0-9_]*$``."""
    return bool(_VALID_IDENT.fullmatch(candidate))
