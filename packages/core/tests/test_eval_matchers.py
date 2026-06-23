"""Tests for the deterministic eval value matchers."""

from __future__ import annotations

import pytest

from elliot_core.eval.matchers import (
    match_normalized,
    match_numeric,
    match_regex,
    match_scientific,
    match_value,
)

# ── numeric ─────────────────────────────────────────────────────────────────


def test_numeric_strips_currency_and_separators():
    # The motivating bug: "$11,614.72" should match a ground truth of 11614.72.
    assert match_numeric("$11,614.72", "11614.72") is True


def test_numeric_rounds_to_expected_decimal_places():
    # 87.2475... rounds to 87.25 at the 2 dp written in the expected literal.
    assert match_numeric("87.2475569858549", "87.25") is True


def test_numeric_rejects_when_rounded_values_differ():
    assert match_numeric("87.26", "87.25") is False


def test_numeric_abs_tol_overrides_default():
    assert match_numeric(87.24, 87.25, abs_tol=0.02) is True
    assert match_numeric(87.20, 87.25, abs_tol=0.02) is False


def test_numeric_rel_tol():
    assert match_numeric(1010, 1000, rel_tol=0.02) is True
    assert match_numeric(1030, 1000, rel_tol=0.02) is False


def test_numeric_rel_tol_zero_expected_uses_denominator_one():
    assert match_numeric(0.005, 0, rel_tol=0.01) is True


def test_numeric_non_numeric_is_false():
    assert match_numeric("not a number", "5") is False
    assert match_numeric(None, "5") is False


def test_numeric_bool_is_not_a_number():
    assert match_numeric(True, "1") is False


def test_numeric_percent_sign_stripped():
    assert match_numeric("4.46%", "4.46") is True


# ── scientific ──────────────────────────────────────────────────────────────


def test_scientific_matches_to_expected_sig_figs():
    assert match_scientific("3.614181818e-19", "3.61e-19") is True


def test_scientific_rejects_when_sig_figs_differ():
    assert match_scientific("3.69e-19", "3.61e-19") is False


def test_scientific_explicit_sig_figs():
    assert match_scientific("3.614e-19", "3.6e-19", sig_figs=2) is True


def test_scientific_zero_only_matches_zero():
    assert match_scientific(0, "0") is True
    assert match_scientific("1e-19", "0") is False


def test_scientific_non_numeric_is_false():
    assert match_scientific("abc", "3.61e-19") is False


# ── normalized ──────────────────────────────────────────────────────────────


def test_normalized_numeric_path():
    assert match_normalized("$2,000", "2000") is True


def test_normalized_string_case_and_space_insensitive():
    assert match_normalized("  Active ", "active") is True


def test_normalized_string_mismatch():
    assert match_normalized("pro", "enterprise") is False


# ── regex ───────────────────────────────────────────────────────────────────


def test_regex_full_match():
    assert match_regex("3.61e-19", r"\d\.\d+e-\d+") is True


def test_regex_must_be_full_match():
    assert match_regex("value=3.61e-19", r"\d\.\d+e-\d+") is False


def test_regex_invalid_pattern_is_false():
    assert match_regex("anything", r"[unclosed") is False


# ── dispatch ────────────────────────────────────────────────────────────────


def test_match_value_exact():
    assert match_value("2", "2", "exact") is True
    assert match_value("2.0", "2", "exact") is False


def test_match_value_routes_each_mode():
    assert match_value("$11,614.72", "11614.72", "numeric") is True
    assert match_value("3.614e-19", "3.61e-19", "scientific") is True
    assert match_value(" Active ", "active", "normalized") is True
    assert match_value("2", r"\d", "regex") is True


def test_match_value_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown match mode"):
        match_value("a", "a", "fuzzy")  # type: ignore[arg-type]
