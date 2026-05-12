"""Tests for elliot_core.sqlite.type_inferrer."""

from __future__ import annotations

from elliot_core.sqlite.type_inferrer import detect_format, infer_column_type


def test_infer_empty_samples() -> None:
    assert infer_column_type([]) == "TEXT"


def test_infer_all_null() -> None:
    assert infer_column_type([None, None]) == "TEXT"


def test_infer_booleans() -> None:
    assert infer_column_type([True, False, True]) == "INTEGER"


def test_infer_integers() -> None:
    assert infer_column_type([1, 2, 3]) == "INTEGER"


def test_infer_large_integer_becomes_text() -> None:
    assert infer_column_type([2**54]) == "TEXT"


def test_infer_floats() -> None:
    assert infer_column_type([1.1, 2.2]) == "REAL"


def test_infer_mixed_int_float() -> None:
    assert infer_column_type([1, 2.5]) == "REAL"


def test_infer_strings() -> None:
    assert infer_column_type(["hello", "world"]) == "TEXT"


def test_detect_format_iso_date() -> None:
    assert detect_format("2024-01-15") == "iso_date"
    assert detect_format("2024-01-15T10:30:00Z") == "iso_date"


def test_detect_format_uuid() -> None:
    assert detect_format("550e8400-e29b-41d4-a716-446655440000") == "uuid"


def test_detect_format_email() -> None:
    assert detect_format("user@example.com") == "email"


def test_detect_format_boolean_string() -> None:
    assert detect_format("true") == "boolean_string"
    assert detect_format("False") == "boolean_string"


def test_detect_format_none() -> None:
    assert detect_format("just a string") is None
