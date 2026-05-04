from __future__ import annotations

import hashlib
import json
from typing import Any

from elliot_core.sqlite.column_namer import safe_name
from elliot_core.sqlite.type_inferrer import infer_column_type
from elliot_core.types.sqlite import ColumnMeta


def detect_schema(rows: list[dict[str, Any]]) -> list[ColumnMeta]:
    if not rows:
        return []
    keys: list[str] = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)
    return [
        ColumnMeta(
            name=safe_name(key),
            sqlite_type=infer_column_type([row.get(key) for row in rows]),
            nullable=any(row.get(key) is None for row in rows),
        )
        for key in keys
    ]


def schema_fingerprint(cols: list[ColumnMeta]) -> str:
    """SHA-256 of sorted column names+types. Stable across runs."""
    key = json.dumps(sorted((c.name, c.sqlite_type) for c in cols))
    return hashlib.sha256(key.encode()).hexdigest()
