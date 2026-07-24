"""Runner for .eval.yaml evaluation suites against a ConnectorConfig."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from elliot_core.eval.matchers import match_value

from .eval_types import EvalCase, EvalSuite
from .tokens import estimate_tokens
from .types import ConnectorConfig

log = structlog.get_logger(__name__)


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    result_rows: int
    token_estimate: int
    duration_ms: float
    error: str | None
    failures: list[str] = field(default_factory=list)


def _check_expectations(
    case: EvalCase,
    rows: list[dict[str, Any]],
    error: str | None,
    error_code: str | None,
    token_estimate: int,
) -> list[str]:
    e = case.expect
    failures: list[str] = []

    if e.error_code:
        if error_code != e.error_code:
            failures.append(f"Expected error_code={e.error_code!r}, got {error_code!r}")
    elif e.no_error and error:
        failures.append(f"Unexpected error: {error}")

    if len(rows) < e.min_rows:
        failures.append(f"Expected >= {e.min_rows} rows, got {len(rows)}")
    if e.max_rows is not None and len(rows) > e.max_rows:
        failures.append(f"Expected <= {e.max_rows} rows, got {len(rows)}")

    for f_name in e.fields_present:
        if rows and f_name not in rows[0]:
            failures.append(f"Field '{f_name}' missing from results")

    if e.all_rows_match:
        arm = e.all_rows_match
        for i, row in enumerate(rows):
            actual = row.get(arm.field)
            if not match_value(
                actual,
                arm.value,
                arm.match,
                abs_tol=arm.abs_tol,
                rel_tol=arm.rel_tol,
                sig_figs=arm.sig_figs,
            ):
                failures.append(
                    f"Row {i}: expected {arm.field}={arm.value!r} ({arm.match}), got {actual!r}"
                )

    for fa in e.field_assertions:
        if not rows:
            failures.append(f"Field assertion '{fa.field}': no rows returned")
            continue
        if fa.row >= len(rows):
            failures.append(
                f"Field assertion '{fa.field}': row {fa.row} out of range ({len(rows)} rows)"
            )
            continue
        actual = rows[fa.row].get(fa.field)
        if not match_value(
            actual,
            fa.equals,
            fa.match,
            abs_tol=fa.abs_tol,
            rel_tol=fa.rel_tol,
            sig_figs=fa.sig_figs,
        ):
            failures.append(
                f"Field '{fa.field}' (row {fa.row}): expected {fa.equals!r} "
                f"({fa.match}), got {actual!r}"
            )

    if e.max_token_estimate and token_estimate > e.max_token_estimate:
        failures.append(f"Token estimate {token_estimate} exceeds limit {e.max_token_estimate}")

    return failures


class EvalRunner:
    def __init__(self, config: ConnectorConfig, secrets: dict[str, str] | None = None) -> None:
        # Use elliot-core's own ToolExecutor. The previous import reached into
        # elliot_connector_runtime — a downstream package elliot-core does not
        # depend on — so a standalone elliot-core install raised ImportError
        # the moment an EvalRunner was constructed.
        from elliot_core.tools.executor import ToolExecutor

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
                case_id=case.id,
                passed=False,
                result_rows=0,
                token_estimate=0,
                duration_ms=0,
                error=f"Tool '{case.tool_id}' not found in connector",
                failures=[f"Tool '{case.tool_id}' not found"],
            )

        t0 = time.monotonic()
        error_str: str | None = None
        rows: list[dict[str, Any]] = []
        error_code: str | None = None

        try:
            # core's ToolExecutor.execute takes the tool id, not the object.
            query_result = await self._executor.execute(case.tool_id, case.arguments)
            rows = query_result.rows
        except Exception as exc:
            error_str = str(exc)
            error_code = getattr(exc, "code", None)

        duration_ms = (time.monotonic() - t0) * 1000
        # The SAME estimate the runtime trace and dashboard report, so an
        # author's max_token_estimate budget means what they see there — not a
        # cruder chars/4 figure that passes/fails a budget the runtime wouldn't.
        token_estimate = estimate_tokens(rows)

        failures = _check_expectations(case, rows, error_str, error_code, token_estimate)
        log.info(
            "eval.case.result",
            case_id=case.id,
            passed=len(failures) == 0,
            rows=len(rows),
        )
        return CaseResult(
            case_id=case.id,
            passed=len(failures) == 0,
            result_rows=len(rows),
            token_estimate=token_estimate,
            duration_ms=round(duration_ms, 1),
            error=error_str,
            failures=failures,
        )
