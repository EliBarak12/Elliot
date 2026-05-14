"""Tests for elliot_core.sql identifier guard."""

from __future__ import annotations

import pytest

from elliot_core.errors import ElliotError
from elliot_core.sql import is_valid_ident, safe_ident

# ── safe_ident ─────────────────────────────────────────────────────────────


def test_safe_ident_accepts_plain():
    assert safe_ident("users") == '"users"'
    assert safe_ident("_internal") == '"_internal"'
    assert safe_ident("col_1") == '"col_1"'
    assert safe_ident("UpperCase") == '"UpperCase"'


def test_safe_ident_rejects_leading_digit():
    with pytest.raises(ElliotError) as exc:
        safe_ident("1tab")
    assert exc.value.code == "INVALID_IDENTIFIER"


def test_safe_ident_rejects_quote():
    with pytest.raises(ElliotError):
        safe_ident('user"; DROP TABLE users; --')


def test_safe_ident_rejects_semicolon():
    with pytest.raises(ElliotError):
        safe_ident("users; DROP TABLE x")


def test_safe_ident_rejects_space():
    with pytest.raises(ElliotError):
        safe_ident("user table")


def test_safe_ident_rejects_dash():
    with pytest.raises(ElliotError):
        safe_ident("user-table")


def test_safe_ident_rejects_empty():
    with pytest.raises(ElliotError):
        safe_ident("")


def test_safe_ident_rejects_none_or_non_string():
    with pytest.raises(ElliotError):
        safe_ident(None)  # type: ignore[arg-type]
    with pytest.raises(ElliotError):
        safe_ident(42)  # type: ignore[arg-type]


def test_safe_ident_length_cap():
    long_name = "a" * 63
    # exactly 63 chars passes (1 + 62 trailing)
    safe_ident(long_name)
    too_long = "a" * 64
    with pytest.raises(ElliotError):
        safe_ident(too_long)


def test_is_valid_ident_matches():
    assert is_valid_ident("ok")
    assert not is_valid_ident("bad-name")
    assert not is_valid_ident("")
