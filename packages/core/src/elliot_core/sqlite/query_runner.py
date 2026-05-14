from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from elliot_core.errors import ElliotError

if TYPE_CHECKING:
    from elliot_core.sqlite.engine import SQLiteEngine

DDL_PATTERN = re.compile(
    r"\b(DROP|CREATE|ALTER|INSERT|UPDATE|DELETE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|REPLACE)\b",
    re.IGNORECASE,
)

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(sql: str) -> str:
    """Strip ``-- line`` and ``/* block */`` comments.

    Audit finding C3: the previous validator only stripped ``--`` comments, so
    ``SELECT/*; DROP TABLE x; --*/ 1`` could smuggle DDL past the
    ``;``-rejection check.
    """
    no_block = _BLOCK_COMMENT.sub(" ", sql)
    return _LINE_COMMENT.sub("", no_block).strip()


def validate_tool_sql(sql: str) -> tuple[bool, str]:
    """Return (True, "") if valid SELECT, or (False, reason) if not."""
    no_comments = _strip_comments(sql)
    if not no_comments:
        return False, "SQL is empty"
    # Trailing single semicolon is fine; embedded ones imply multiple statements.
    if ";" in no_comments.rstrip(";"):
        return False, "Multiple statements not allowed"
    m = DDL_PATTERN.search(no_comments)
    if m:
        return False, f"Forbidden keyword: {m.group()}"
    if not no_comments.upper().lstrip().startswith(("SELECT", "WITH")):
        return False, "SQL must start with SELECT or WITH"
    return True, ""


def run_tool_query(
    engine: SQLiteEngine,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    valid, reason = validate_tool_sql(sql)
    if not valid:
        raise ElliotError("INVALID_SQL", reason)
    return engine.query(sql, params or {})
