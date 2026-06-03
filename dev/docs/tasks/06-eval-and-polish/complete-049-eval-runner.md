# 049 — Evaluation Runner

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 021

## Objective
Deterministic **Python** evaluation: run YAML-defined test cases directly against the `ToolExecutor` and score the results. No HTTP server needed.

## Files to Create

### `packages/core/src/elliot_core/eval/__init__.py` (empty)

### `packages/core/src/elliot_core/eval/models.py`
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class EvalCase:
    id: str
    tool_id: str
    params: dict[str, Any]
    expected_rows: list[dict] | None = None
    match_mode: Literal["exact", "contains", "shape"] = "contains"
    description: str = ""


@dataclass
class EvalSuite:
    id: str
    name: str
    cases: list[EvalCase]


@dataclass
class EvalCaseResult:
    case_id: str
    tool_id: str
    passed: bool
    actual_rows: list[dict]
    latency_ms: float
    error: str | None = None


@dataclass
class EvalRunResult:
    suite_id: str
    run_at: str       # ISO 8601
    score: float      # 0.0–100.0
    passed: int
    failed: int
    cases: list[EvalCaseResult]
```

### `packages/core/src/elliot_core/eval/runner.py`
```python
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from elliot_core.eval.models import EvalCase, EvalCaseResult, EvalRunResult, EvalSuite
from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig


async def run_eval_suite(
    suite: EvalSuite,
    executor: ToolExecutor,
    connector: ConnectorConfig,
) -> EvalRunResult:
    tool_map = {t.id: t for t in connector.tools}
    results: list[EvalCaseResult] = []

    for case in suite.cases:
        tool = tool_map.get(case.tool_id)
        if tool is None:
            results.append(EvalCaseResult(
                case_id=case.id, tool_id=case.tool_id,
                passed=False, actual_rows=[], latency_ms=0.0,
                error=f"Tool not found: {case.tool_id}",
            ))
            continue

        t0 = time.monotonic()
        try:
            result = await executor.execute(tool, case.params)
            latency_ms = (time.monotonic() - t0) * 1000
            passed = _score(result.rows, case.expected_rows, case.match_mode)
            results.append(EvalCaseResult(
                case_id=case.id, tool_id=case.tool_id,
                passed=passed, actual_rows=result.rows, latency_ms=round(latency_ms, 2),
            ))
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            results.append(EvalCaseResult(
                case_id=case.id, tool_id=case.tool_id,
                passed=False, actual_rows=[], latency_ms=round(latency_ms, 2), error=str(exc),
            ))

    passed_n = sum(1 for r in results if r.passed)
    total = len(results)
    return EvalRunResult(
        suite_id=suite.id,
        run_at=datetime.datetime.utcnow().isoformat() + "Z",
        score=round(passed_n / total * 100, 1) if total else 100.0,
        passed=passed_n,
        failed=total - passed_n,
        cases=results,
    )


def _score(actual: list[dict], expected: list[dict] | None, mode: str) -> bool:
    if expected is None:
        return True
    if mode == "exact":
        return actual == expected
    if mode == "shape":
        if len(actual) != len(expected):
            return False
        return (set(actual[0]) == set(expected[0])) if actual and expected else True
    # "contains" (default): every expected row must appear somewhere in actual
    return all(
        any(all(row.get(k) == v for k, v in exp.items()) for row in actual)
        for exp in expected
    )


# ── Storage ────────────────────────────────────────────────────────────────────────────────

def save_result(result: EvalRunResult, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = result.run_at.replace(":", "-")[:19]
    path = directory / f"{stem}-{result.suite_id}.json"
    path.write_text(json.dumps(result.__dict__, default=str, indent=2), encoding="utf-8")
    return path


def load_results(directory: Path) -> list[EvalRunResult]:
    if not directory.exists():
        return []
    results = []
    for p in sorted(directory.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append(EvalRunResult(**data))
        except Exception:
            pass
    return results


def detect_regressions(prev: EvalRunResult, curr: EvalRunResult) -> list[str]:
    """Return case IDs that passed in prev but fail in curr."""
    prev_passed = {r.case_id for r in prev.cases if r.passed}
    return [r.case_id for r in curr.cases if not r.passed and r.case_id in prev_passed]
```

## Done When
- [ ] Suite with all passing cases returns `score == 100.0`
- [ ] Suite with one failing case returns `score < 100`
- [ ] `detect_regressions` returns case IDs that regressed
- [ ] `save_result` / `load_results` round-trip correctly
- [ ] Unknown `tool_id` in a case returns `passed=False, error="Tool not found: ..."`
