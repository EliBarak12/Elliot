"""Tests for elliot_core.tools.schema_inspector."""

from __future__ import annotations

import pytest

from elliot_core.tools.schema_inspector import ColumnInfo, TableSchema, _infer_type, schema_to_dict


def test_infer_type_bool() -> None:
    assert _infer_type(True) == "boolean"


def test_infer_type_int() -> None:
    assert _infer_type(42) == "integer"


def test_infer_type_float() -> None:
    assert _infer_type(3.14) == "number"


def test_infer_type_string() -> None:
    assert _infer_type("hello") == "string"
    assert _infer_type(None) == "string"


def test_schema_to_dict_shape() -> None:
    schema = TableSchema(
        source_id="db",
        table_name="users",
        columns=[ColumnInfo(name="id", type="integer", nullable=False)],
        sample_rows=[{"id": 1}],
        row_count_estimate=100,
    )
    d = schema_to_dict(schema)
    assert d["source_id"] == "db"
    assert d["table"] == "users"
    assert d["columns"][0]["name"] == "id"
    assert d["row_count_estimate"] == 100


def test_schema_to_dict_empty() -> None:
    schema = TableSchema(source_id="api", table_name="")
    d = schema_to_dict(schema)
    assert d["columns"] == []
    assert d["sample_rows"] == []
    assert d["row_count_estimate"] is None


@pytest.mark.asyncio
async def test_inspect_file_source_empty() -> None:
    from elliot_core.tools.schema_inspector import inspect_file_source

    class FakeResult:
        rows: list[dict] = []

    class FakeFetcher:
        async def fetch(self) -> FakeResult:
            return FakeResult()

    class FakeSource:
        id = "file1"
        path = "data.json"

    schema = await inspect_file_source(FakeSource(), lambda _: FakeFetcher())
    assert schema.columns == []
    assert schema.row_count_estimate == 0


@pytest.mark.asyncio
async def test_inspect_file_source_with_rows() -> None:
    from elliot_core.tools.schema_inspector import inspect_file_source

    class FakeResult:
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}, {"id": 3, "name": "Carol"}]

    class FakeFetcher:
        async def fetch(self) -> FakeResult:
            return FakeResult()

    class FakeSource:
        id = "file1"
        path = "data.json"

    schema = await inspect_file_source(FakeSource(), lambda _: FakeFetcher())
    assert len(schema.columns) == 2
    assert schema.columns[0].name == "id"
    assert schema.columns[0].type == "integer"
    assert schema.row_count_estimate == 3
