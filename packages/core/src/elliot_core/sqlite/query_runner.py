from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from elliot_core.errors import ElliotError

if TYPE_CHECKING:
    from elliot_core.sqlite.engine import SQLiteEngine

DDL_PATTERN = re.compile(
    r"\b(DROP|CREATE|ALTER|INSERT|UPDATE|DELETE|ATTACH|DETACH|PRAGMA)\b",
    re.IGNORECASE,
)


def validate_tool_sql(sql: str) -> tuple[bool, str]:
    """Return (True, "") if valid SELECT, or (False, reason) if not."""
    stripped = sql.strip()
    no_comments = re.sub(r"--[^\n]*", "", stripped).strip()
    if not no_comments:
        return False, "SQL is empty"
    if ";" in no_comments:
        return False, "Multiple statements not allowed"
    m = DDL_PATTERN.search(no_comments)
    if m:
        return False, f"Forbidden keyword: {m.group()}"
    if not no_comments.upper().startswith("SELECT"):
        return False, "SQL must start with SELECT"
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
