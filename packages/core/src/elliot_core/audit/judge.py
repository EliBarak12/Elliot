"""Deterministic judge for connector audit transcripts.

Borrowed from Petri's design: a transcript is the signal, not a pass/fail bit.
The judge scores every transcript on graded 1-10 dimensions (higher = better)
and emits findings that cite the exact tool call that triggered them, so an
agent can act on them directly.

The judge is intentionally deterministic — it scores observable transcript
structure (errors, retries, token sizes, completion) rather than calling a
model — so audits are reproducible and unit-testable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from elliot_core.audit.models import (
    AuditFinding,
    AuditReport,
    AuditToolCall,
    AuditTranscript,
    DimensionScore,
)
from elliot_core.types.connector import ConnectorConfig

log = structlog.get_logger(__name__)

# A result above this estimated token count is "oversized" — Elliot principle 2
# says results are sized for context windows, not raw dumps.
OVERSIZED_TOKEN_ESTIMATE = 1200

# Error codes that indicate the agent could not understand the tool's schema.
_SCHEMA_ERROR_CODES = frozenset(
    {"MISSING_PARAM", "INVALID_PARAM_TYPE", "INVALID_PARAM", "VALIDATION_ERROR"}
)
# Error codes that indicate the agent picked or named the wrong tool.
_SELECTION_ERROR_CODES = frozenset({"TOOL_NOT_FOUND", "INVALID_TOOL", "UNKNOWN_TOOL"})

# Phrases that mark an error message as actionable (tells the agent a next step).
_ACTIONABLE_HINTS = (
    "try ",
    "use ",
    "call ",
    "must ",
    "expected",
    "instead",
    "provide",
    "valid",
    "e.g",
    "example",
    "available",
    "did you mean",
    "required",
    "should be",
)

# Gate thresholds.
_MIN_SUCCESS_RATE = 0.6

# One tool call located within its transcript: (seed_id, call_index, call).
_Call = tuple[str, int, AuditToolCall]


def _score(ratio: float) -> float:
    """Map a 0-1 quality ratio onto a 1-10 score."""
    return round(1.0 + 9.0 * max(0.0, min(1.0, ratio)), 1)


def _is_actionable(message: str | None) -> bool:
    if not message:
        return False
    low = message.lower()
    return any(hint in low for hint in _ACTIONABLE_HINTS)


def _evidence(seed_id: str, index: int, call: AuditToolCall) -> str:
    return f"{seed_id} call #{index + 1}: {call.tool_id}({call.arguments})"


def _suggestion_for(call: AuditToolCall) -> str:
    code = (call.error_code or "").upper()
    if code in _SCHEMA_ERROR_CODES:
        return (
            "Clarify the parameter: tighten its name, description, type, or add "
            "an enum so the agent passes the right value first time."
        )
    if code in _SELECTION_ERROR_CODES:
        return (
            "The agent called a tool that does not exist or does not fit. "
            "Make tool names/descriptions distinct and verb-first."
        )
    if not _is_actionable(call.error_message):
        return (
            "Rewrite the error message to state the next step the agent should "
            "take (which tool to call, what valid value looks like)."
        )
    return "Investigate why this call failed and make recovery obvious to the agent."


def _collect_findings(
    transcripts: list[AuditTranscript],
    *,
    error_calls: list[_Call],
    unknown_tool_calls: list[_Call],
    oversized_calls: list[_Call],
) -> list[AuditFinding]:
    """Turn the pre-bucketed problem calls into citable AuditFindings.

    One finding per incomplete task, unknown-tool call, failed call (bucketed
    into a dimension by error code / actionability), and oversized result.
    """
    findings: list[AuditFinding] = []

    for tr in transcripts:
        if not tr.task_completed:
            findings.append(
                AuditFinding(
                    dimension="task_completion",
                    severity="warning",
                    tool_id=None,
                    message=f"Audit agent could not complete task '{tr.seed_id}'.",
                    evidence=f"{tr.seed_id}: {tr.summary or tr.task}",
                    suggestion=(
                        "Check whether a needed tool is missing, mis-described, "
                        "or returns the wrong fields for this task."
                    ),
                )
            )

    for seed_id, idx, call in unknown_tool_calls:
        findings.append(
            AuditFinding(
                dimension="tool_selection",
                severity="error",
                tool_id=call.tool_id,
                message=(
                    f"Audit agent called '{call.tool_id}', which the connector does not expose."
                ),
                evidence=_evidence(seed_id, idx, call),
                suggestion=(
                    "Either the agent hallucinated a tool (descriptions are too "
                    "vague) or a tool the task needs is missing."
                ),
            )
        )

    for seed_id, idx, call in error_calls:
        code = (call.error_code or "ERROR").upper()
        if code in _SCHEMA_ERROR_CODES:
            dimension = "schema_clarity"
        elif code in _SELECTION_ERROR_CODES:
            dimension = "tool_selection"
        elif not _is_actionable(call.error_message):
            dimension = "error_actionability"
        else:
            dimension = "tool_reliability"
        findings.append(
            AuditFinding(
                dimension=dimension,
                severity="warning",
                tool_id=call.tool_id,
                message=f"[{code}] {call.error_message or 'tool call failed'}",
                evidence=_evidence(seed_id, idx, call),
                suggestion=_suggestion_for(call),
            )
        )

    for seed_id, idx, call in oversized_calls:
        findings.append(
            AuditFinding(
                dimension="token_efficiency",
                severity="warning",
                tool_id=call.tool_id,
                message=(
                    f"'{call.tool_id}' returned ~{call.result_token_estimate} "
                    f"tokens (over the {OVERSIZED_TOKEN_ESTIMATE} budget)."
                ),
                evidence=_evidence(seed_id, idx, call),
                suggestion=(
                    "Add or lower a LIMIT, return fewer fields, or add a filter "
                    "parameter so the agent can scope the result."
                ),
            )
        )

    return findings


def _build_dimension_scores(
    *,
    transcripts: list[AuditTranscript],
    completed: int,
    success_rate: float,
    all_calls: list[_Call],
    error_calls: list[_Call],
    schema_errors: list[_Call],
    selection_errors: list[_Call],
    unknown_tool_calls: list[_Call],
    oversized_calls: list[_Call],
    nonactionable_errors: list[_Call],
    total_tokens: int,
    tool_ids: set[str],
) -> list[DimensionScore]:
    """Build the seven graded (1-10) dimension scores from the aggregates."""
    total_calls = len(all_calls)

    def ratio(bad: int) -> float:
        return 1.0 - (bad / total_calls) if total_calls else 1.0

    actionable_errors = len(error_calls) - len(nonactionable_errors)
    distinct_tools_used = {c.tool_id for _, _, c in all_calls} & tool_ids
    coverage = len(distinct_tools_used) / len(tool_ids) if tool_ids else 1.0

    return [
        DimensionScore(
            dimension="task_completion",
            score=_score(success_rate),
            justification=f"{completed}/{len(transcripts)} audit tasks completed.",
        ),
        DimensionScore(
            dimension="tool_reliability",
            score=_score(ratio(len(error_calls))),
            justification=f"{len(error_calls)}/{total_calls} tool calls failed.",
        ),
        DimensionScore(
            dimension="error_actionability",
            score=_score(actionable_errors / len(error_calls) if error_calls else 1.0),
            justification=(
                f"{actionable_errors}/{len(error_calls)} errors told the agent a next step."
                if error_calls
                else "No tool calls failed."
            ),
        ),
        DimensionScore(
            dimension="token_efficiency",
            score=_score(ratio(len(oversized_calls))),
            justification=(
                f"{len(oversized_calls)}/{total_calls} calls returned an "
                f"oversized result; ~{total_tokens} tokens total."
            ),
        ),
        DimensionScore(
            dimension="schema_clarity",
            score=_score(ratio(len(schema_errors))),
            justification=f"{len(schema_errors)} call(s) failed on parameter/schema confusion.",
        ),
        DimensionScore(
            dimension="tool_selection",
            score=_score(ratio(len(selection_errors) + len(unknown_tool_calls))),
            justification=(
                f"{len(selection_errors) + len(unknown_tool_calls)} call(s) hit "
                "a missing or wrong tool."
            ),
        ),
        DimensionScore(
            dimension="scenario_coverage",
            score=_score(coverage),
            justification=(
                f"{len(distinct_tools_used)}/{len(tool_ids)} connector tools "
                "were exercised by the audit."
            ),
        ),
    ]


def judge_audit(
    transcripts: list[AuditTranscript],
    config: ConnectorConfig,
) -> AuditReport:
    """Score ``transcripts`` against ``config`` and return an :class:`AuditReport`."""
    tool_ids = {t.id for t in config.tools}

    all_calls: list[_Call] = [
        (tr.seed_id, idx, call) for tr in transcripts for idx, call in enumerate(tr.calls)
    ]
    total_calls = len(all_calls)
    error_calls = [(s, i, c) for s, i, c in all_calls if not c.ok]
    completed = sum(1 for tr in transcripts if tr.task_completed)
    success_rate = completed / len(transcripts) if transcripts else 0.0
    total_tokens = sum(c.result_token_estimate or 0 for _, _, c in all_calls)

    schema_errors = [
        t for t in error_calls if (t[2].error_code or "").upper() in _SCHEMA_ERROR_CODES
    ]
    selection_errors = [
        t for t in error_calls if (t[2].error_code or "").upper() in _SELECTION_ERROR_CODES
    ]
    unknown_tool_calls = [t for t in all_calls if t[2].tool_id not in tool_ids]
    oversized_calls = [
        (s, i, c)
        for s, i, c in all_calls
        if (c.result_token_estimate or 0) > OVERSIZED_TOKEN_ESTIMATE
    ]
    nonactionable_errors = [t for t in error_calls if not _is_actionable(t[2].error_message)]

    findings = _collect_findings(
        transcripts,
        error_calls=error_calls,
        unknown_tool_calls=unknown_tool_calls,
        oversized_calls=oversized_calls,
    )

    dimension_scores = _build_dimension_scores(
        transcripts=transcripts,
        completed=completed,
        success_rate=success_rate,
        all_calls=all_calls,
        error_calls=error_calls,
        schema_errors=schema_errors,
        selection_errors=selection_errors,
        unknown_tool_calls=unknown_tool_calls,
        oversized_calls=oversized_calls,
        nonactionable_errors=nonactionable_errors,
        total_tokens=total_tokens,
        tool_ids=tool_ids,
    )

    error_count = sum(1 for f in findings if f.severity == "error")
    passed = error_count == 0 and success_rate >= _MIN_SUCCESS_RATE
    min_dim = min((d.score for d in dimension_scores), default=10.0)
    summary = (
        f"{'PASSED' if passed else 'NEEDS WORK'} — {completed}/{len(transcripts)} "
        f"tasks completed, {len(error_calls)}/{total_calls} calls failed, "
        f"{len(findings)} finding(s), lowest dimension score {min_dim}."
    )

    report = AuditReport(
        connector_slug=config.slug,
        run_at=datetime.now(UTC).isoformat(),
        seed_count=len(transcripts),
        transcript_count=len(transcripts),
        task_success_rate=round(success_rate, 3),
        total_tool_calls=total_calls,
        error_call_count=len(error_calls),
        total_token_estimate=total_tokens,
        dimension_scores=dimension_scores,
        findings=findings,
        passed=passed,
        summary=summary,
    )
    log.info(
        "audit.judged",
        slug=config.slug,
        passed=passed,
        findings=len(findings),
        success_rate=report.task_success_rate,
    )
    return report
