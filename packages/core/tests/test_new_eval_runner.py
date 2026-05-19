"""Tests for elliot_core.eval_runner (CLI eval runner)."""

from __future__ import annotations

import pytest

from elliot_core.eval_runner import _check_expectations
from elliot_core.eval_types import EvalCase, EvalExpect, EvalSuite, ExpectRowsMatch


def _case(**kwargs) -> EvalCase:  # type: ignore[type-arg]
    return EvalCase(id="c", tool_id="t", **kwargs)


def test_no_failures_for_clean_result() -> None:
    case = _case(expect=EvalExpect(min_rows=1))
    rows = [{"id": 1}]
    failures = _check_expectations(case, rows, None, None, 10)
    assert failures == []


def test_min_rows_failure() -> None:
    case = _case(expect=EvalExpect(min_rows=3))
    failures = _check_expectations(case, [{"a": 1}], None, None, 10)
    assert any("3" in f for f in failures)


def test_max_rows_failure() -> None:
    case = _case(expect=EvalExpect(max_rows=1))
    failures = _check_expectations(case, [{"a": 1}, {"a": 2}], None, None, 10)
    assert any("2" in f for f in failures)


def test_unexpected_error_failure() -> None:
    case = _case(expect=EvalExpect(no_error=True))
    failures = _check_expectations(case, [], "SQL error", None, 0)
    assert any("SQL error" in f for f in failures)


def test_expected_error_code_match() -> None:
    case = _case(expect=EvalExpect(error_code="NOT_FOUND"))
    failures = _check_expectations(case, [], "not found", "NOT_FOUND", 0)
    assert failures == []


def test_expected_error_code_mismatch() -> None:
    case = _case(expect=EvalExpect(error_code="NOT_FOUND"))
    failures = _check_expectations(case, [], "bad sql", "INVALID_SQL", 0)
    assert any("NOT_FOUND" in f for f in failures)


def test_fields_present_failure() -> None:
    case = _case(expect=EvalExpect(fields_present=["id", "name"]))
    failures = _check_expectations(case, [{"id": 1}], None, None, 10)
    assert any("name" in f for f in failures)


def test_all_rows_match_failure() -> None:
    case = _case(expect=EvalExpect(all_rows_match=ExpectRowsMatch(field="species", value="dog")))
    rows = [{"species": "dog"}, {"species": "cat"}]
    failures = _check_expectations(case, rows, None, None, 20)
    assert len(failures) == 1
    assert "cat" in failures[0]


def test_max_token_estimate_failure() -> None:
    case = _case(expect=EvalExpect(max_token_estimate=5))
    failures = _check_expectations(case, [], None, None, 100)
    assert any("100" in f for f in failures)


@pytest.mark.asyncio
async def test_eval_runner_tool_not_found() -> None:
    from elliot_core.eval_runner import EvalRunner
    from elliot_core.types import ConnectorConfig

    config = ConnectorConfig(name="T", slug="t", version="1.0.0", sources=[], tools=[])
    runner = EvalRunner(config)
    suite = EvalSuite(
        name="S",
        connector="t",
        cases=[EvalCase(id="c1", tool_id="nonexistent", arguments={})],
    )
    results = await runner.run_suite(suite)
    assert len(results) == 1
    assert results[0].passed is False
    assert "not found" in results[0].failures[0]


def test_score_shape_same_keys_same_length() -> None:
    from elliot_core.eval.runner import _score

    actual = [{"id": 1, "name": "a"}]
    expected = [{"id": 2, "name": "b"}]
    assert _score(actual, expected, "shape") is True


def test_score_shape_empty_returns_true() -> None:
    from elliot_core.eval.runner import _score

    assert _score([], [], "shape") is True


def test_load_results_skips_corrupt_files(tmp_path):
    from elliot_core.eval.runner import load_results

    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON")
    results = load_results(tmp_path)
    assert results == []


async def test_eval_runner_constructs_without_connector_runtime_import() -> None:
    """EvalRunner must build using elliot-core's own ToolExecutor — the old
    code imported elliot_connector_runtime, which elliot-core does not depend
    on, so constructing an EvalRunner raised ImportError."""
    from elliot_core.eval_runner import EvalRunner
    from elliot_core.types.connector import ConnectorConfig

    config = ConnectorConfig(name="X", slug="x", version="1.0.0", tools=[], sources=[])
    runner = EvalRunner(config)
    suite = EvalSuite(
        name="s",
        connector="x",
        cases=[EvalCase(id="c1", tool_id="missing_tool", arguments={})],
    )
    results = await runner.run_suite(suite)
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].case_id == "c1"
