"""Tests for schema_detector: detect_schema and schema_fingerprint."""

from __future__ import annotations

from elliot_core.sources.schema_detector import detect_schema, schema_fingerprint


def test_detect_schema_empty_rows():
    assert detect_schema([]) == []


def test_detect_schema_infers_columns():
    rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    cols = detect_schema(rows)
    names = [c.name for c in cols]
    assert "id" in names
    assert "name" in names


def test_detect_schema_marks_nullable():
    rows = [{"id": 1, "note": None}, {"id": 2, "note": "hi"}]
    cols = detect_schema(rows)
    note_col = next(c for c in cols if c.name == "note")
    assert note_col.nullable is True


def test_detect_schema_not_nullable_when_always_present():
    rows = [{"id": 1}, {"id": 2}]
    cols = detect_schema(rows)
    id_col = next(c for c in cols if c.name == "id")
    assert id_col.nullable is False


def test_detect_schema_union_of_keys_across_rows():
    rows = [{"a": 1}, {"b": 2}]
    cols = detect_schema(rows)
    names = [c.name for c in cols]
    assert "a" in names
    assert "b" in names


def test_schema_fingerprint_is_stable():
    rows = [{"id": 1, "name": "Alice"}]
    cols = detect_schema(rows)
    fp1 = schema_fingerprint(cols)
    fp2 = schema_fingerprint(cols)
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex


def test_schema_fingerprint_differs_for_different_schemas():
    cols_a = detect_schema([{"id": 1}])
    cols_b = detect_schema([{"name": "x"}])
    assert schema_fingerprint(cols_a) != schema_fingerprint(cols_b)
