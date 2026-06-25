"""Tests for the shared SQL helpers in elliot_core.sql.

Covers the CTE-aware table extraction that stops ``validate_sql`` /
``build_connector`` from false-flagging working ``WITH`` tools (P0-B), the
Unicode identifier rule that lets non-ASCII column names survive (P1), and the
bind-param / select-star helpers.
"""

from __future__ import annotations

import pytest

from elliot_core.errors import ElliotError
from elliot_core.sql import (
    extract_cte_names,
    extract_sql_params,
    extract_table_names,
    has_select_star,
    is_valid_ident,
    referenced_base_tables,
    safe_ident,
)

# ── CTE extraction (P0-B) ─────────────────────────────────────────────────────


def test_extract_cte_names_single():
    sql = "WITH recent AS (SELECT * FROM doctors) SELECT * FROM recent"
    assert extract_cte_names(sql) == ["recent"]


def test_extract_cte_names_multiple_and_recursive():
    sql = "WITH RECURSIVE tree AS (SELECT 1), leaves AS (SELECT * FROM tree) SELECT * FROM leaves"
    assert extract_cte_names(sql) == ["tree", "leaves"]


def test_extract_cte_names_none_without_with():
    assert extract_cte_names("SELECT * FROM doctors") == []


def test_referenced_base_tables_excludes_ctes():
    sql = (
        "WITH recent AS (SELECT * FROM doctors WHERE active = 1) "
        "SELECT * FROM recent JOIN clinics ON recent.cid = clinics.id"
    )
    # ``recent`` is a CTE alias and must NOT appear as a base table; the real
    # tables ``doctors`` and ``clinics`` must.
    base = referenced_base_tables(sql)
    assert "recent" not in base
    assert "doctors" in base and "clinics" in base


def test_referenced_base_tables_keeps_subquery_alias_source():
    # A derived-table alias (``sub``) is not a CTE; the real table inside it is
    # what must be reported.
    sql = "SELECT * FROM (SELECT id FROM real_table) AS sub"
    assert referenced_base_tables(sql) == ["real_table"]


def test_extract_table_names_still_returns_all_refs():
    # The raw extractor is unchanged for callers that want every FROM/JOIN ref.
    sql = "WITH x AS (SELECT * FROM t) SELECT * FROM x"
    assert extract_table_names(sql) == ["t", "x"]


# ── Unicode identifiers (P1) ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["שם", "מספר_רישיון", "ville", "café", "店名"])
def test_is_valid_ident_accepts_unicode_letters(name: str):
    assert is_valid_ident(name)
    assert safe_ident(name) == f'"{name}"'


@pytest.mark.parametrize("bad", ['a"b', "a;b", "a b", "1col", "a-b", ""])
def test_is_valid_ident_still_rejects_unsafe(bad: str):
    assert not is_valid_ident(bad)
    with pytest.raises(ElliotError):
        safe_ident(bad)


def test_is_valid_ident_length_bound():
    assert is_valid_ident("a" * 63)
    assert not is_valid_ident("a" * 64)


# ── bind params / select star ─────────────────────────────────────────────────


def test_extract_sql_params():
    assert extract_sql_params("SELECT * FROM t WHERE price < :max_price AND id = :id") == [
        "max_price",
        "id",
    ]


def test_has_select_star():
    assert has_select_star("SELECT * FROM t")
    assert not has_select_star("SELECT COUNT(*) FROM t")
