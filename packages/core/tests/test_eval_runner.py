"""Tests for the eval runner: score, regressions, save/load, unknown tool."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from elliot_core.eval.models import EvalCase, EvalCaseResult, EvalRunResult, EvalSuite
from elliot_core.eval.runner import (
    _score,
    detect_regressions,
    load_results,
    run_eval_suite,
    save_result,
)
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ToolDefinition, ToolResult


def _make_connector(*tool_ids: str) -> ConnectorConfig:
    tools = [
        ToolDefinition(
            id=tid,
            name=tid,
            description=f"Tool {tid}",
            category="READ",
            source_ids=["src"],
        )
        for tid in tool_ids
    ]
    source = SourceConfig(id="src", name="Source", type="rest", url="https://example.com")
    return ConnectorConfig(
        name="test", slug="test", version="1", description="", sources=[source], tools=tools
    )


def _make_executor(rows: list[dict[str, Any]]) -> Any:
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=ToolResult(rows=rows, meta={"row_count": len(rows)}))
    return executor


# ── _score unit tests ──────────────────────────────────────────────────────────


def test_score_none_expected_always_passes():
    assert _score([{"a": 1}], None, "contains") is True


def test_score_exact_match():
    rows = [{"id": "1", "name": "Alice"}]
    assert _score(rows, rows, "exact") is True


def test_score_exact_mismatch():
    assert _score([{"id": "1"}], [{"id": "2"}], "exact") is False


def test_score_contains_all_present():
    rows = [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]
    assert _score(rows, [{"name": "Alice"}], "contains") is True


def test_score_contains_missing():
    rows = [{"id": "1", "name": "Alice"}]
    assert _score(rows, [{"name": "Carol"}], "contains") is False


def test_score_shape_same_columns():
    actual = [{"a": 1, "b": 2}]
    expected = [{"a": 99, "b": 0}]
    assert _score(actual, expected, "shape") is True


def test_score_shape_different_length():
    assert _score([{"a": 1}], [{"a": 1}, {"a": 2}], "shape") is False


# ── run_eval_suite ─────────────────────────────────────────────────────────────


async def test_all_passing_score_100():
    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[EvalCase(id="c1", tool_id="get_users", params={})],
    )
    connector = _make_connector("get_users")
    executor = _make_executor([{"id": "1"}])

    result = await run_eval_suite(suite, executor, connector)

    assert result.score == 100.0
    assert result.passed == 1
    assert result.failed == 0


async def test_one_failing_case_lowers_score():
    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[
            EvalCase(id="c1", tool_id="get_users", params={}, expected_rows=[{"id": "999"}]),
        ],
    )
    connector = _make_connector("get_users")
    executor = _make_executor([{"id": "1"}])

    result = await run_eval_suite(suite, executor, connector)

    assert result.score < 100.0
    assert result.failed == 1


async def test_unknown_tool_id_returns_failed_with_error():
    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[EvalCase(id="c1", tool_id="no_such_tool", params={})],
    )
    connector = _make_connector("get_users")
    executor = _make_executor([])

    result = await run_eval_suite(suite, executor, connector)

    assert result.passed == 0
    assert result.cases[0].passed is False
    assert "Tool not found: no_such_tool" in (result.cases[0].error or "")


async def test_empty_suite_returns_score_100():
    suite = EvalSuite(id="s1", name="Empty", cases=[])
    connector = _make_connector("get_users")
    executor = _make_executor([])

    result = await run_eval_suite(suite, executor, connector)

    assert result.score == 100.0
    assert result.passed == 0
    assert result.failed == 0


async def test_executor_exception_recorded_as_failed():
    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[EvalCase(id="c1", tool_id="get_users", params={})],
    )
    connector = _make_connector("get_users")
    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=RuntimeError("network error"))

    result = await run_eval_suite(suite, executor, connector)

    assert result.failed == 1
    assert result.cases[0].error == "network error"


# ── expect_error: validating the error paths, not just the happy path ──────────


async def test_expect_error_passes_when_tool_raises_the_expected_code():
    from elliot_core.errors import ElliotError

    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[
            EvalCase(
                id="c1",
                tool_id="get_users",
                params={"status": "bogus"},
                expect_error="INVALID_PARAM_VALUE",
            )
        ],
    )
    connector = _make_connector("get_users")
    executor = MagicMock()
    executor.execute = AsyncMock(
        side_effect=ElliotError("INVALID_PARAM_VALUE", "status must be one of [a, b]")
    )

    result = await run_eval_suite(suite, executor, connector)

    assert result.passed == 1
    assert result.cases[0].passed is True
    assert result.cases[0].error is None


async def test_expect_error_matches_a_message_fragment_too():
    from elliot_core.errors import ElliotError

    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[EvalCase(id="c1", tool_id="get_users", params={}, expect_error="must be one of")],
    )
    connector = _make_connector("get_users")
    executor = MagicMock()
    executor.execute = AsyncMock(
        side_effect=ElliotError("INVALID_PARAM_VALUE", "status must be one of [a, b]")
    )

    result = await run_eval_suite(suite, executor, connector)
    assert result.passed == 1


async def test_expect_error_fails_when_the_call_unexpectedly_succeeds():
    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[
            EvalCase(id="c1", tool_id="get_users", params={}, expect_error="INVALID_PARAM_VALUE")
        ],
    )
    connector = _make_connector("get_users")
    executor = _make_executor([{"id": "1"}])

    result = await run_eval_suite(suite, executor, connector)
    assert result.failed == 1
    assert "but the call succeeded" in (result.cases[0].error or "")


async def test_expect_error_fails_on_a_different_error():
    from elliot_core.errors import ElliotError

    suite = EvalSuite(
        id="s1",
        name="Suite",
        cases=[
            EvalCase(id="c1", tool_id="get_users", params={}, expect_error="INVALID_PARAM_VALUE")
        ],
    )
    connector = _make_connector("get_users")
    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=ElliotError("UPSTREAM_FETCH_FAILED", "boom"))

    result = await run_eval_suite(suite, executor, connector)
    assert result.failed == 1
    assert "Expected an error containing 'INVALID_PARAM_VALUE'" in (result.cases[0].error or "")


# ── save/load round-trip ───────────────────────────────────────────────────────


def test_save_and_load_round_trip():
    run = EvalRunResult(
        suite_id="s1",
        run_at="2026-01-01T00:00:00+00:00",
        score=75.0,
        passed=3,
        failed=1,
        cases=[
            EvalCaseResult(case_id="c1", tool_id="t1", passed=True, actual_rows=[], latency_ms=5.0),
            EvalCaseResult(
                case_id="c2",
                tool_id="t1",
                passed=False,
                actual_rows=[],
                latency_ms=3.0,
                error="oops",
            ),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_result(run, Path(tmpdir))
        assert path.exists()

        loaded = load_results(Path(tmpdir))

    assert len(loaded) == 1
    assert loaded[0].suite_id == "s1"
    assert loaded[0].score == 75.0
    assert loaded[0].passed == 3
    assert loaded[0].failed == 1
    assert len(loaded[0].cases) == 2
    assert loaded[0].cases[1].error == "oops"


def test_load_results_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        results = load_results(Path(tmpdir))
    assert results == []


def test_load_results_missing_dir():
    results = load_results(Path("/nonexistent/path/xyz"))
    assert results == []


# ── detect_regressions ─────────────────────────────────────────────────────────


def test_detect_regressions_returns_regressed_case_ids():
    prev = EvalRunResult(
        suite_id="s1",
        run_at="2026-01-01T00:00:00Z",
        score=100.0,
        passed=2,
        failed=0,
        cases=[
            EvalCaseResult(case_id="c1", tool_id="t1", passed=True, actual_rows=[], latency_ms=1.0),
            EvalCaseResult(case_id="c2", tool_id="t1", passed=True, actual_rows=[], latency_ms=1.0),
        ],
    )
    curr = EvalRunResult(
        suite_id="s1",
        run_at="2026-01-02T00:00:00Z",
        score=50.0,
        passed=1,
        failed=1,
        cases=[
            EvalCaseResult(case_id="c1", tool_id="t1", passed=True, actual_rows=[], latency_ms=1.0),
            EvalCaseResult(
                case_id="c2", tool_id="t1", passed=False, actual_rows=[], latency_ms=1.0
            ),
        ],
    )

    regressions = detect_regressions(prev, curr)

    assert regressions == ["c2"]


def test_detect_regressions_no_regressions():
    run = EvalRunResult(
        suite_id="s1",
        run_at="2026-01-01T00:00:00Z",
        score=100.0,
        passed=1,
        failed=0,
        cases=[
            EvalCaseResult(case_id="c1", tool_id="t1", passed=True, actual_rows=[], latency_ms=1.0)
        ],
    )
    assert detect_regressions(run, run) == []


def test_detect_regressions_new_failure_not_regression():
    prev = EvalRunResult(
        suite_id="s1",
        run_at="2026-01-01T00:00:00Z",
        score=100.0,
        passed=1,
        failed=0,
        cases=[
            EvalCaseResult(case_id="c1", tool_id="t1", passed=True, actual_rows=[], latency_ms=1.0)
        ],
    )
    curr = EvalRunResult(
        suite_id="s1",
        run_at="2026-01-02T00:00:00Z",
        score=50.0,
        passed=1,
        failed=1,
        cases=[
            EvalCaseResult(case_id="c1", tool_id="t1", passed=True, actual_rows=[], latency_ms=1.0),
            EvalCaseResult(
                case_id="c2", tool_id="t1", passed=False, actual_rows=[], latency_ms=1.0
            ),
        ],
    )
    assert detect_regressions(prev, curr) == []
