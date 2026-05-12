from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ColumnMeta(BaseModel):
    name: str
    sqlite_type: Literal["INTEGER", "REAL", "TEXT"] = "TEXT"
    nullable: bool = True


class FlattenedTable(BaseModel):
    name: str
    columns: list[ColumnMeta]
    rows: list[dict[str, Any]]


class FlattenWarning(BaseModel):
    type: Literal["depth_exceeded", "circular_reference", "array_truncated", "wide_object_serialized"]
    path: str
    message: str


class FlattenResult(BaseModel):
    primary_table: FlattenedTable
    related_tables: list[FlattenedTable] = []
    warnings: list[FlattenWarning] = []
