"""Shared SQL identifier and statement guards.

Centralises:

- :func:`safe_ident` — validate and quote a table/column identifier so we can
  safely interpolate it into SQL even when the surrounding value is influenced
  by connector authors or agents. This is the only place identifier
  interpolation should originate from.
- :func:`postgres_quote_ident` — `Identifier` quoting for psycopg, used when
  the value is destined for ``cursor.execute`` against postgres.

Why this exists
---------------
Pydantic models (TableDefinition, ColumnDefinition, FilterCondition,
ReturnField) accept identifiers as plain strings. Several callsites used to
do ``f'... "{name}"'`` style interpolation. Per audit finding C3, a ``"``
inside ``name`` breaks out of the identifier quote. We never want to depend
on the upstream model rejecting hostile names — defend at the SQL boundary.
"""

from __future__ import annotations

import re

from elliot_core.errors import ElliotError

# An identifier is an unreserved word: starts with letter or underscore,
# followed by letters / digits / underscores. Bounded length so a connector
# can't ship a 10MB identifier and DoS the SQL engine via memory pressure.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def safe_ident(name: str) -> str:
    """Validate ``name`` as a SQL identifier and return it double-quoted.

    Raises :class:`~elliot_core.errors.ElliotError` ``INVALID_IDENTIFIER`` if
    ``name`` does not match ``^[A-Za-z_][A-Za-z0-9_]{0,62}$``.

    The returned value is wrapped in double quotes (the SQL-standard
    identifier quote, accepted by sqlite, postgres, and mysql with
    ``ANSI_QUOTES``), e.g. ``users`` → ``"users"``. Because the input has
    already been validated, the resulting string is safe to f-string into
    any SQL statement.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ElliotError(
            "INVALID_IDENTIFIER",
            "identifier must match ^[A-Za-z_][A-Za-z0-9_]{0,62}$",
            detail={"value": str(name)[:64]},
        )
    return f'"{name}"'


def is_valid_ident(name: str) -> bool:
    """Return True iff ``name`` is a valid SQL identifier under :func:`safe_ident`'s rules."""
    return isinstance(name, str) and bool(_IDENT_RE.match(name))


_TABLE_REF_RE = re.compile(
    r"(?:FROM|JOIN)\s+(?:\"([^\"]+)\"|`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))",
    re.IGNORECASE,
)


def extract_table_names(sql: str) -> list[str]:
    """Pull every table identifier that appears after ``FROM`` or ``JOIN``.

    Used to decide which sources a tool actually queries — so the runtime
    only materializes the sources the tool's SQL references, not every
    source in the connector. A bearer-auth failure on an unrelated source
    used to break every tool because tool.source_ids was set to "all"; with
    this helper the auto-assignment narrows to just the tables the SQL
    touches.

    Quoting: tables may appear as ``"name"``, `` `name` ``, or bare. The
    return order is the first-occurrence order in the SQL, with duplicates
    removed.
    """
    seen: list[str] = []
    for match in _TABLE_REF_RE.finditer(sql or ""):
        name = next((g for g in match.groups() if g), None)
        if name and name not in seen:
            seen.append(name)
    return seen


# A SQLite named bind parameter: ``:name`` where name starts with a letter or
# underscore. The leading-letter rule avoids matching time literals (``12:30``)
# and Postgres-style ``::cast`` as parameters.
_BIND_PARAM_RE = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def extract_sql_params(sql: str) -> list[str]:
    """Pull every ``:name`` bind parameter referenced in ``sql``.

    Used to verify at tool-create time that every parameter the SQL binds is
    actually declared on the tool (audit B2): an undeclared ``:max_fast``
    used to register fine and only blow up at call time with a cryptic
    "no such parameter" from SQLite. Order is first-occurrence, deduped.
    """
    seen: list[str] = []
    for match in _BIND_PARAM_RE.finditer(sql or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


# ``SELECT *`` / ``SELECT t.*`` projection. ``COUNT(*)`` and other aggregates
# are fine — only a bare star *projection* is the token-bloat / unstable-contract
# footgun the linter cares about, so we anchor to SELECT and allow an optional
# ``DISTINCT`` and a single ``table.`` qualifier.
_SELECT_STAR_RE = re.compile(r"\bSELECT\s+(?:DISTINCT\s+)?(?:[A-Za-z_]\w*\.)?\*", re.IGNORECASE)


def has_select_star(sql: str) -> bool:
    """True if ``sql`` projects ``SELECT *`` (or ``SELECT t.*``).

    A star projection returns every column of the underlying snapshot, which
    bloats the agent's context and makes the tool's output schema drift
    whenever the upstream shape changes — the opposite of a typed contract
    (audit B2 / principle 2). ``COUNT(*)`` and ``*`` inside expressions are
    not matched.
    """
    return bool(_SELECT_STAR_RE.search(sql or ""))
