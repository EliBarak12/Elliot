from __future__ import annotations

import json
from typing import Any

from elliot_core.sqlite.column_namer import deduplicate_names, safe_name
from elliot_core.sqlite.type_inferrer import infer_column_type
from elliot_core.types.sqlite import ColumnMeta, FlattenedTable, FlattenResult, FlattenWarning

MAX_DEPTH = 5
MAX_ARRAY_ROWS = 1000
_MAX_INLINE_KEYS = (
    10  # dicts with more keys are serialized as JSON TEXT to prevent column explosion
)


def flatten(data: list[Any], table_name: str) -> FlattenResult:
    """Flatten a list of JSON objects into SQLite-ready tables."""
    warnings: list[FlattenWarning] = []
    child_tables: dict[str, list[dict[str, Any]]] = {}

    primary_rows: list[dict[str, Any]] = []
    for item in data:
        row = _flatten_obj(item, table_name, table_name, 0, frozenset(), child_tables, warnings)
        primary_rows.append(row)

    primary_table = FlattenedTable(
        name=table_name,
        columns=_build_columns(primary_rows),
        rows=primary_rows,
    )
    related = [
        FlattenedTable(name=name, columns=_build_columns(rows), rows=rows)
        for name, rows in child_tables.items()
    ]
    return FlattenResult(primary_table=primary_table, related_tables=related, warnings=warnings)


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53:
        return str(value)
    return value


def _flatten_obj(
    obj: Any,
    table_name: str,
    warning_path: str,
    depth: int,
    visited: frozenset[int],
    child_tables: dict[str, list[dict[str, Any]]],
    warnings: list[FlattenWarning],
) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {"value": _scalar(obj)}

    if id(obj) in visited:
        warnings.append(
            FlattenWarning(
                type="circular_reference",
                path=warning_path,
                message=f"Circular reference detected at {warning_path}",
            )
        )
        return {"value": "[Circular]"}

    visited = visited | {id(obj)}
    row: dict[str, Any] = {}

    for key, value in obj.items():
        col = safe_name(key)
        _process_field(
            col, value, table_name, warning_path, depth, visited, row, child_tables, warnings
        )

    return row


def _process_field(
    col: str,
    value: Any,
    table_name: str,
    warning_path: str,
    depth: int,
    visited: frozenset[int],
    row: dict[str, Any],
    child_tables: dict[str, list[dict[str, Any]]],
    warnings: list[FlattenWarning],
) -> None:
    field_path = f"{warning_path}.{col}"

    if value is None or isinstance(value, (str, int, float, bool)):
        row[col] = _scalar(value)

    elif isinstance(value, dict):
        if depth >= MAX_DEPTH:
            warnings.append(
                FlattenWarning(
                    type="depth_exceeded",
                    path=field_path,
                    message=f"Depth limit {MAX_DEPTH} exceeded at {field_path}, serialized as TEXT",
                )
            )
            row[col] = json.dumps(value)
        elif len(value) > _MAX_INLINE_KEYS:
            warnings.append(
                FlattenWarning(
                    type="wide_object_serialized",
                    path=field_path,
                    message=(
                        f"Object at {field_path} has {len(value)} keys "
                        f"(>{_MAX_INLINE_KEYS}), serialized as JSON TEXT to prevent column explosion"
                    ),
                )
            )
            row[col] = json.dumps(value)
        elif id(value) in visited:
            warnings.append(
                FlattenWarning(
                    type="circular_reference",
                    path=field_path,
                    message=f"Circular reference at {field_path}",
                )
            )
            row[col] = "[Circular]"
        else:
            child_table_name = f"{table_name}_{col}"
            sub = _flatten_obj(
                value, child_table_name, field_path, depth + 1, visited, child_tables, warnings
            )
            for sub_key, sub_val in sub.items():
                row[f"{col}_{sub_key}"] = sub_val

    elif isinstance(value, list):
        child_name = f"{table_name}_{col}"
        if not value:
            # Rule 12: empty array → empty child table
            if child_name not in child_tables:
                child_tables[child_name] = []
        elif all(isinstance(item, (str, int, float, bool, type(None))) for item in value):
            # Rule 3: array of primitives → JSON TEXT
            row[col] = json.dumps(value)
        else:
            # Rule 4: array of objects → child table
            items: list[Any] = value
            if len(items) > MAX_ARRAY_ROWS:
                warnings.append(
                    FlattenWarning(
                        type="array_truncated",
                        path=field_path,
                        message=(
                            f"Array truncated from {len(items)} to {MAX_ARRAY_ROWS} "
                            f"rows at {field_path}"
                        ),
                    )
                )
                items = items[:MAX_ARRAY_ROWS]

            if child_name not in child_tables:
                child_tables[child_name] = []

            for idx, item in enumerate(items):
                child_row = _flatten_obj(
                    item,
                    child_name,
                    f"{field_path}[{idx}]",
                    depth + 1,
                    visited,
                    child_tables,
                    warnings,
                )
                child_tables[child_name].append({"_parent_id": None, "_index": idx, **child_row})
    else:
        try:
            row[col] = json.dumps(value)
        except (TypeError, ValueError):
            row[col] = str(value)


def _build_columns(rows: list[dict[str, Any]]) -> list[ColumnMeta]:
    if not rows:
        return []
    keys: list[str] = []
    for row in rows:
        for k in row:
            if k not in keys:
                keys.append(k)
    deduped = deduplicate_names(keys)
    columns: list[ColumnMeta] = []
    for original, name in zip(keys, deduped, strict=True):
        samples = [row.get(original) for row in rows]
        sqlite_type = infer_column_type(samples)
        nullable = any(s is None for s in samples)
        columns.append(ColumnMeta(name=name, sqlite_type=sqlite_type, nullable=nullable))
    return columns
