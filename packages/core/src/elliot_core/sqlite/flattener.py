from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from elliot_core.sqlite.column_namer import deduplicate_names, safe_name
from elliot_core.sqlite.type_inferrer import infer_column_type
from elliot_core.types.sqlite import ColumnMeta, FlattenedTable, FlattenResult, FlattenWarning

MAX_DEPTH = 5
MAX_ARRAY_ROWS = 1000
_MAX_INLINE_KEYS = (
    10  # dicts with more keys are serialized as JSON TEXT to prevent column explosion
)


@dataclass
class _FlattenState:
    """Accumulators threaded through the whole flatten of one dataset.

    Bundled so the recursive helpers take one ``state`` instead of passing
    these three around individually. All three are mutated in place:
    ``child_tables`` collects synthetic child-table rows, ``warnings`` collects
    FlattenWarnings, and ``counters`` holds the per-table monotonic ``_id``.
    """

    child_tables: dict[str, list[dict[str, Any]]]
    warnings: list[FlattenWarning]
    counters: dict[str, int]


def flatten(data: list[Any], table_name: str) -> FlattenResult:
    """Flatten a list of JSON objects into SQLite-ready tables.

    Each output row carries an ``_id`` (sequential within its table) and,
    for child rows produced by a nested ``array-of-objects`` field, a
    ``_parent_id`` pointing at the parent row's ``_id``. These columns
    let connector authors write JOINs across the synthetic table tree
    (``parent JOIN child ON child._parent_id = parent._id``) when the
    upstream JSON has no natural foreign key — e.g.
    ``insights[].teaserblocks[]`` where each teaserblock is anonymously
    nested under its insight.
    """
    warnings: list[FlattenWarning] = []
    child_tables: dict[str, list[dict[str, Any]]] = {}
    # Per-table monotonic counter — produces stable, dense ``_id`` values
    # without depending on SQLite's ``rowid`` (which the runtime cannot
    # rely on across re-materialisations).
    counters: dict[str, int] = {table_name: 0}
    state = _FlattenState(child_tables=child_tables, warnings=warnings, counters=counters)

    primary_rows: list[dict[str, Any]] = []
    for item in data:
        counters[table_name] += 1
        my_id = counters[table_name]
        row = _flatten_obj(
            item,
            table_name,
            table_name,
            0,
            frozenset(),
            state,
            parent_id=None,
            my_id=my_id,
        )
        # ``_id`` is the canonical column name agents write JOINs against.
        row["_id"] = my_id
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
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


def _flatten_obj(
    obj: Any,
    table_name: str,
    warning_path: str,
    depth: int,
    visited: frozenset[int],
    state: _FlattenState,
    *,
    parent_id: int | None,
    my_id: int,
) -> dict[str, Any]:
    """Flatten a single object. ``my_id`` is this row's ``_id`` value
    (assigned by the caller before recursing); list-of-objects fields
    pass it down as ``parent_id`` so each child row can reference its
    specific parent. Nested-object fields inline into this row, so they
    don't get their own id/parent_id."""
    if not isinstance(obj, dict):
        return {"value": _scalar(obj)}

    if id(obj) in visited:
        state.warnings.append(
            FlattenWarning(
                type="circular_reference",
                path=warning_path,
                message=f"Circular reference detected at {warning_path}",
            )
        )
        return {"value": "[Circular]"}

    visited = visited | {id(obj)}
    row: dict[str, Any] = {}
    if parent_id is not None:
        row["_parent_id"] = parent_id

    for key, value in obj.items():
        col = safe_name(key)
        _process_field(
            col,
            value,
            table_name,
            warning_path,
            depth,
            visited,
            row,
            state,
            my_id=my_id,
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
    state: _FlattenState,
    *,
    my_id: int,
) -> None:
    field_path = f"{warning_path}.{col}"

    if value is None or isinstance(value, (str, int, float, bool)):
        row[col] = _scalar(value)

    elif isinstance(value, dict):
        if depth >= MAX_DEPTH:
            state.warnings.append(
                FlattenWarning(
                    type="depth_exceeded",
                    path=field_path,
                    message=f"Depth limit {MAX_DEPTH} exceeded at {field_path}, serialized as TEXT",
                )
            )
            row[col] = json.dumps(value)
        elif len(value) > _MAX_INLINE_KEYS:
            state.warnings.append(
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
            state.warnings.append(
                FlattenWarning(
                    type="circular_reference",
                    path=field_path,
                    message=f"Circular reference at {field_path}",
                )
            )
            row[col] = "[Circular]"
        else:
            child_table_name = f"{table_name}_{col}"
            # Nested *object* (not array) — its fields inline into the
            # current row, so it's not a separate table; pass ``my_id`` as
            # both my_id and parent_id (any deeper list-of-objects under
            # this object will still link back to the current row).
            sub = _flatten_obj(
                value,
                child_table_name,
                field_path,
                depth + 1,
                visited,
                state,
                parent_id=None,
                my_id=my_id,
            )
            for sub_key, sub_val in sub.items():
                row[f"{col}_{sub_key}"] = sub_val

    elif isinstance(value, list):
        child_name = f"{table_name}_{col}"
        if not value:
            # Rule 12: empty array → empty child table
            if child_name not in state.child_tables:
                state.child_tables[child_name] = []
        elif all(isinstance(item, (str, int, float, bool, type(None))) for item in value):
            # Rule 3: array of primitives → JSON TEXT
            row[col] = json.dumps(value)
        else:
            # Rule 4: array of objects → child table
            items: list[Any] = value
            if len(items) > MAX_ARRAY_ROWS:
                state.warnings.append(
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

            if child_name not in state.child_tables:
                state.child_tables[child_name] = []
            state.counters.setdefault(child_name, 0)

            for idx, item in enumerate(items):
                state.counters[child_name] += 1
                child_id = state.counters[child_name]
                child_row = _flatten_obj(
                    item,
                    child_name,
                    f"{field_path}[{idx}]",
                    depth + 1,
                    visited,
                    state,
                    parent_id=my_id,
                    my_id=child_id,
                )
                child_row["_id"] = child_id
                child_row.setdefault("_index", idx)
                state.child_tables[child_name].append(child_row)
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
