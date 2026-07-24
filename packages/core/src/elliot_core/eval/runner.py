from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any

import structlog

from elliot_core.eval.models import EvalCaseResult, EvalRunResult, EvalSuite
from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig

log = structlog.get_logger(__name__)


async def run_eval_suite(
    suite: EvalSuite,
    executor: ToolExecutor,
    connector: ConnectorConfig,
) -> EvalRunResult:
    tool_ids = {t.id for t in connector.tools}
    results: list[EvalCaseResult] = []

    for case in suite.cases:
        if case.tool_id not in tool_ids:
            results.append(
                EvalCaseResult(
                    case_id=case.id,
                    tool_id=case.tool_id,
                    passed=False,
                    actual_rows=[],
                    latency_ms=0.0,
                    error=f"Tool not found: {case.tool_id}",
                )
            )
            continue

        t0 = time.monotonic()
        try:
            result = await executor.execute(case.tool_id, case.params)
            latency_ms = (time.monotonic() - t0) * 1000
            if case.expect_error:
                # The case asserts a failure, but the call succeeded → fail it.
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        tool_id=case.tool_id,
                        passed=False,
                        actual_rows=result.rows,
                        latency_ms=round(latency_ms, 2),
                        error=(
                            f"Expected an error containing '{case.expect_error}', "
                            "but the call succeeded."
                        ),
                    )
                )
            else:
                passed = _score(result.rows, case.expected_rows, case.match_mode)
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        tool_id=case.tool_id,
                        passed=passed,
                        actual_rows=result.rows,
                        latency_ms=round(latency_ms, 2),
                    )
                )
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            if case.expect_error:
                # The error IS the asserted outcome — pass iff the expected text
                # appears in the error CODE or its message (so an author can
                # assert either "INVALID_PARAM_VALUE" or a message fragment).
                haystack = f"{getattr(exc, 'code', '')} {exc}".lower()
                matched = case.expect_error.lower() in haystack
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        tool_id=case.tool_id,
                        passed=matched,
                        actual_rows=[],
                        latency_ms=round(latency_ms, 2),
                        error=(
                            None
                            if matched
                            else f"Expected an error containing '{case.expect_error}', got: {exc}"
                        ),
                    )
                )
            else:
                log.warning(
                    "eval.case.error", case_id=case.id, tool_id=case.tool_id, error=str(exc)
                )
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        tool_id=case.tool_id,
                        passed=False,
                        actual_rows=[],
                        latency_ms=round(latency_ms, 2),
                        error=str(exc),
                    )
                )

    passed_n = sum(1 for r in results if r.passed)
    total = len(results)
    score = round(passed_n / total * 100, 1) if total else 100.0

    log.info(
        "eval.suite.complete",
        suite_id=suite.id,
        score=score,
        passed=passed_n,
        failed=total - passed_n,
    )

    return EvalRunResult(
        suite_id=suite.id,
        run_at=datetime.datetime.now(datetime.UTC).isoformat(),
        score=score,
        passed=passed_n,
        failed=total - passed_n,
        cases=results,
    )


def _score(actual: list[dict[str, Any]], expected: list[dict[str, Any]] | None, mode: str) -> bool:
    if expected is None:
        return True
    if mode == "exact":
        return actual == expected
    if mode == "shape":
        if len(actual) != len(expected):
            return False
        if actual and expected:
            return set(actual[0].keys()) == set(expected[0].keys())
        return True
    # "contains": every expected row must appear somewhere in actual
    return all(
        any(all(row.get(k) == v for k, v in exp.items()) for row in actual) for exp in expected
    )


def save_result(result: EvalRunResult, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = result.run_at.replace(":", "-")[:19]
    path = directory / f"{stem}-{result.suite_id}.json"
    path.write_text(
        json.dumps(
            {
                "suite_id": result.suite_id,
                "run_at": result.run_at,
                "score": result.score,
                "passed": result.passed,
                "failed": result.failed,
                "cases": [vars(c) for c in result.cases],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def load_results(directory: Path) -> list[EvalRunResult]:
    if not directory.exists():
        return []
    results = []
    for p in sorted(directory.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            cases = [EvalCaseResult(**c) for c in data.pop("cases", [])]
            results.append(EvalRunResult(**data, cases=cases))
        except Exception:
            pass
    return results


def detect_regressions(prev: EvalRunResult, curr: EvalRunResult) -> list[str]:
    prev_passed = {r.case_id for r in prev.cases if r.passed}
    return [r.case_id for r in curr.cases if not r.passed and r.case_id in prev_passed]
