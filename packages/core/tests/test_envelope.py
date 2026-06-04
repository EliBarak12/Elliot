"""Tests for the shared response-envelope row extractor.

This module is the single source of truth for how both the design-time REST
fetcher and the runtime executor locate the records array inside a JSON
payload, so its behavior is pinned here independently of either caller.
"""

from __future__ import annotations

from elliot_core.sources.envelope import (
    extract_rows,
    looks_like_unextracted_envelope,
)

# ── top-level shapes (parity with the historical behavior) ────────────────────


def test_bare_list_returned_as_is():
    assert extract_rows([{"id": 1}]) == [{"id": 1}]


def test_standard_key_data():
    assert extract_rows({"data": [{"id": 2}]}) == [{"id": 2}]


def test_standard_key_items():
    assert extract_rows({"items": [{"id": 3}]}) == [{"id": 3}]


def test_single_dict_wrapped_as_one_row():
    assert extract_rows({"id": 1}) == [{"id": 1}]


def test_resource_named_array_autodetected():
    # dummyjson-style: pagination scalars + exactly one object-array.
    data = {"total": 100, "skip": 0, "limit": 30, "products": [{"id": 1}, {"id": 2}]}
    assert extract_rows(data) == [{"id": 1}, {"id": 2}]


def test_multiple_top_level_arrays_are_ambiguous():
    data = {"products": [{"id": 1}], "categories": [{"id": 2}]}
    assert extract_rows(data) == [data]


def test_scalar_array_is_not_a_row_set():
    data = {"name": "x", "tags": ["a", "b"]}
    assert extract_rows(data) == [data]


def test_non_dict_non_list_returns_empty():
    assert extract_rows(42) == []
    assert extract_rows(None) == []


# ── nested envelopes (the bug this module fixes) ──────────────────────────────


def test_ckan_package_search_nested_under_result_results():
    # data.gov.il / CKAN Action API: rows live two layers deep.
    data = {
        "help": "https://data.gov.il/api/3/action/help_show",
        "success": True,
        "result": {"count": 2, "facets": {}, "results": [{"id": "a"}, {"id": "b"}]},
    }
    assert extract_rows(data) == [{"id": "a"}, {"id": "b"}]


def test_ckan_organization_list_all_fields_top_level_result_array():
    data = {"help": "...", "success": True, "result": [{"name": "boi"}, {"name": "cbs"}]}
    assert extract_rows(data) == [{"name": "boi"}, {"name": "cbs"}]


def test_nested_data_items_envelope():
    data = {"data": {"items": [{"id": 1}], "total": 1}}
    assert extract_rows(data) == [{"id": 1}]


def test_json_rpc_style_result_wrapper():
    data = {"jsonrpc": "2.0", "id": 1, "result": {"records": [{"x": 1}]}}
    assert extract_rows(data) == [{"x": 1}]


def test_empty_nested_array_yields_zero_rows_not_envelope():
    # A genuinely empty result set must be 0 rows, never the wrapper-as-one-row.
    data = {"success": True, "result": {"count": 0, "results": []}}
    assert extract_rows(data) == []


def test_nested_records_inside_rows_are_not_mistaken_for_the_row_set():
    # `result.results` is the row set; the `tags`/`resources` arrays inside each
    # record must not derail extraction.
    data = {
        "success": True,
        "result": {
            "results": [
                {"id": "a", "tags": [{"t": 1}], "resources": [{"r": 1}]},
                {"id": "b", "tags": [], "resources": []},
            ]
        },
    }
    assert extract_rows(data) == data["result"]["results"]


def test_descent_is_depth_bounded():
    # Records buried below the depth ceiling are not found (wrapped instead),
    # so a pathological payload can't drive an unbounded search.
    data = {"a": {"b": {"c": {"d": {"e": [{"id": 1}]}}}}}
    assert extract_rows(data) == [data]


# ── data_path ─────────────────────────────────────────────────────────────────


def test_data_path_to_array():
    data = {"meta": {"results": [{"id": 1}]}}
    assert extract_rows(data, "meta.results") == [{"id": 1}]


def test_data_path_to_wrapper_object_still_unwraps_inner_array():
    # Pointing data_path at the wrapper object (not the array) still works:
    # the located value is unwrapped with the same envelope logic.
    data = {"result": {"results": [{"id": 9}]}}
    assert extract_rows(data, "result") == [{"id": 9}]


def test_data_path_not_found_returns_empty():
    assert extract_rows({"x": 1}, "missing.path") == []


# ── looks_like_unextracted_envelope (build-time warning signal) ───────────────


def test_warning_signal_fires_on_ambiguous_wrapped_envelope():
    # Two candidate arrays -> wrapped as one row -> builder should be warned.
    data = {"orders": [{"id": 1}], "customers": [{"id": 2}]}
    rows = extract_rows(data)
    assert rows == [data]
    assert looks_like_unextracted_envelope(rows) is True


def test_warning_signal_quiet_on_clean_single_object():
    # A legit single-object resource (no hidden arrays) is not flagged.
    rows = extract_rows({"id": 1, "name": "x"})
    assert looks_like_unextracted_envelope(rows) is False


def test_warning_signal_quiet_when_rows_extracted():
    rows = extract_rows({"result": {"results": [{"id": 1}, {"id": 2}]}})
    assert looks_like_unextracted_envelope(rows) is False
