# Task 063 — Eval Runner

## Goal
Add an `eval` subcommand to the `elliot` CLI that reads a `.eval.yaml` file, runs each case against the live `ToolExecutor`, checks expectations, and prints a pass/fail report with token estimates.

## Why
Test cases defined in task 062 are useless without a runner. The runner closes the loop: write tools → write eval cases → run `elliot eval` → know instantly if the connector is agent-ready.

## File to create

### `packages/core/src/elliot_core/eval_runner.py`

```python
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .eval_types import EvalCase, EvalSuite, load_eval_suite
from .types import ConnectorConfig


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    result_rows: int
    token_estimate: int
    duration_ms: float
    error: str | None
    failures: list[str]   # human-readable failure reasons


class EvalRunner:
    def __init__(self, config: ConnectorConfig, secrets: dict[str, str] | None = None) -> None:
        from elliot_connector_runtime.executor import ToolExecutor
        self._executor = ToolExecutor(config, secrets or {})
        self._config = config

    async def run_suite(self, suite: EvalSuite) -> list[CaseResult]:
        results = []
        for case in suite.cases:
            result = await self._run_case(case)
            results.append(result)
        return results

    async def _run_case(self, case: EvalCase) -> CaseResult:
        tool_map = {t.id: t for t in self._config.tools}
        tool = tool_map.get(case.tool_id)
        if tool is None:
            return CaseResult(
                case_id=case.id, passed=False, result_rows=0,
                token_estimate=0, duration_ms=0,
                error=f"Tool '{case.tool_id}' not found in connector",
                failures=[f"Tool '{case.tool_id}' not found"],
            )

        t0 = time.monotonic()
        error_str = None
        rows: list[dict] = []
        error_code: str | None = None

        try:
            query_result = await self._executor.execute(tool, case.arguments)
            rows = query_result.rows
        except Exception as exc:
            error_str = str(exc)
            # Try to extract error code from ElliotError
            error_code = getattr(exc, "code", None)

        duration_ms = (time.monotonic() - t0) * 1000
        token_estimate = len(json.dumps(rows, default=str)) // 4

        failures = _check_expectations(case, rows, error_str, error_code, token_estimate)
        return CaseResult(
            case_id=case.id,
            passed=len(failures) == 0,
            result_rows=len(rows),
            token_estimate=token_estimate,
            duration_ms=round(duration_ms, 1),
            error=error_str,
            failures=failures,
        )


def _check_expectations(
    case: EvalCase,
    rows: list[dict],
    error: str | None,
    error_code: str | None,
    token_estimate: int,
) -> list[str]:
    e = case.expect
    failures = []

    if e.error_code:
        if error_code != e.error_code:
            failures.append(f"Expected error_code={e.error_code!r}, got {error_code!r}")
    elif e.no_error and error:
        failures.append(f"Unexpected error: {error}")

    if len(rows) < e.min_rows:
        failures.append(f"Expected ≥{e.min_rows} rows, got {len(rows)}")
    if e.max_rows is not None and len(rows) > e.max_rows:
        failures.append(f"Expected ≤{e.max_rows} rows, got {len(rows)}")

    for field in e.fields_present:
        if rows and field not in rows[0]:
            failures.append(f"Field '{field}' missing from results")

    if e.all_rows_match:
        for i, row in enumerate(rows):
            if row.get(e.all_rows_match.field) != e.all_rows_match.value:
                failures.append(
                    f"Row {i}: expected {e.all_rows_match.field}={e.all_rows_match.value!r}, "
                    f"got {row.get(e.all_rows_match.field)!r}"
                )

    if e.max_token_estimate and token_estimate > e.max_token_estimate:
        failures.append(f"Token estimate {token_estimate} exceeds limit {e.max_token_estimate}")

    return failures
```

## CLI command (add `eval` to `elliot_core/cli.py`)

```python
eval_cmd = sub.add_parser("eval", help="Run evaluation cases against a connector")
eval_cmd.add_argument("path", help="Path to .eval.yaml")
eval_cmd.add_argument("--connector", help="Override connector .json path")

if args.command == "eval":
    suite = load_eval_suite(args.path)

    # Infer connector path from suite.connector if not overridden
    connector_path = args.connector or (
        Path(args.path).parent / f"{suite.connector}.connector.json"
    )
    config = load_connector(connector_path)
    runner = EvalRunner(config)
    results = asyncio.run(runner.run_suite(suite))

    passed = sum(1 for r in results if r.passed)
    for r in results:
        icon = "✅" if r.passed else "❌"
        token_warn = " ⚠️ large" if r.token_estimate > 500 else ""
        print(f"{icon}  {r.case_id:<35} {r.result_rows} rows  {r.token_estimate} tokens  {r.duration_ms}ms{token_warn}")
        for fail in r.failures:
            print(f"     └ {fail}")

    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
```

## Tests

```python
import pytest
from elliot_core.eval_runner import EvalRunner, _check_expectations
from elliot_core.eval_types import EvalCase, EvalExpect

def test_check_min_rows_failure():
    case = EvalCase(id="c", tool_id="t", expect=EvalExpect(min_rows=3))
    failures = _check_expectations(case, rows=[{"a":1}], error=None, error_code=None, token_estimate=10)
    assert any("3" in f for f in failures)

def test_check_all_rows_match_failure():
    from elliot_core.eval_types import ExpectRowsMatch
    case = EvalCase(
        id="c", tool_id="t",
        expect=EvalExpect(all_rows_match=ExpectRowsMatch(field="species", value="dog"))
    )
    rows = [{"species": "dog"}, {"species": "cat"}]
    failures = _check_expectations(case, rows=rows, error=None, error_code=None, token_estimate=20)
    assert len(failures) == 1
    assert "cat" in failures[0]

@pytest.mark.asyncio
async def test_eval_runner_pass(connector_file):
    from elliot_core.types import ConnectorConfig
    # Load and run a simple case against the minimal connector
    # (uses respx mock)
    ...
```
