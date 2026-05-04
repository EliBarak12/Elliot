from __future__ import annotations

import re
from typing import Any


def infer_column_type(samples: list[Any]) -> str:
    """Return 'INTEGER', 'REAL', or 'TEXT' based on majority vote over non-null samples."""
    non_null = [s for s in samples if s is not None]
    if not non_null:
        return "TEXT"
    if all(isinstance(v, bool) for v in non_null):
        return "INTEGER"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        if all(abs(v) <= 2**53 for v in non_null):
            return "INTEGER"
        return "TEXT"  # too large for JS-safe int
    if all(isinstance(v, (float, int)) and not isinstance(v, bool) for v in non_null):
        return "REAL"
    return "TEXT"


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[\d:.Z+-]+)?$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


def detect_format(value: str) -> str | None:
    """Detect a semantic format hint for a string value."""
    if ISO_DATE_RE.match(value):
        return "iso_date"
    if UUID_RE.match(value):
        return "uuid"
    if EMAIL_RE.match(value):
        return "email"
    if value.lower() in ("true", "false"):
        return "boolean_string"
    return None
