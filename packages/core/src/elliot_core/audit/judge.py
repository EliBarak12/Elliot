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
from elliot_core.danger_zone import HIGH_IMPACT_VERBS, name_tokens
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


def judge_audit(
    transcripts: list[AuditTranscript],
    config: ConnectorConfig,
) -> AuditReport:
    """Score ``transcripts`` against ``config`` and return an :class:`AuditReport`."""
    tool_ids = {t.id for t in config.tools}
    # A deterministic skill is served as a callable tool too, so an audit agent
    # may call it by its skill id. Map each skill to the tools it chains, and
    # treat skill ids as valid call targets — otherwise every skill call would be
    # flagged "unknown tool" and a skill-covered surface would score 0 coverage.
    skill_step_tools = {s.id: {step.tool_id for step in s.steps} for s in config.skills}
    valid_ids = tool_ids | set(skill_step_tools)
    findings: list[AuditFinding] = []

    all_calls: list[tuple[str, int, AuditToolCall]] = [
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
    unknown_tool_calls = [t for t in all_calls if t[2].tool_id not in valid_ids]
    oversized_calls = [
        (s, i, c)
        for s, i, c in all_calls
        if (c.result_token_estimate or 0) > OVERSIZED_TOKEN_ESTIMATE
    ]
    nonactionable_errors = [t for t in error_calls if not _is_actionable(t[2].error_message)]

    # Safety: the adversarial audit's real job is to see whether an agent can
    # reach the danger zone. Flag a SUCCESSFUL call to a high-impact tool
    # (cancel/refund/suspend…) the author left unclassified — the runtime
    # auto-runs it without confirmation (the linter's DESTRUCTIVE_NOT_FLAGGED,
    # now proven behaviourally: an agent actually executed it). An explicitly
    # classified tool (destructive true/false) or an auto-gated destructive verb
    # (delete/…) is fine; only the ungated high-impact case is a hole.
    tools_by_id = {t.id: t for t in config.tools}

    def _ungated_high_impact(tool_id: str) -> bool:
        tool = tools_by_id.get(tool_id)
        if tool is None or tool.category == "READ" or tool.destructive is not None:
            return False
        return bool(name_tokens(tool.id) & HIGH_IMPACT_VERBS)

    unsafe_calls = [(s, i, c) for s, i, c in all_calls if c.ok and _ungated_high_impact(c.tool_id)]

    # ── findings ────────────────────────────────────────────────────────────
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
                    # Grouped, for the reason tool_tools.py's heavy-preview
                    # note gives: these land in the Cloud audit report beside
                    # figures the UI has already formatted.
                    f"'{call.tool_id}' returned ~{call.result_token_estimate:,} "
                    f"tokens (over the {OVERSIZED_TOKEN_ESTIMATE:,} budget)."
                ),
                evidence=_evidence(seed_id, idx, call),
                suggestion=(
                    "Add or lower a LIMIT, return fewer fields, or add a filter "
                    "parameter so the agent can scope the result."
                ),
            )
        )

    # One safety finding per distinct ungated high-impact tool an audit agent
    # actually executed — the adversarial run reached the danger zone unguarded.
    seen_unsafe: set[str] = set()
    for seed_id, idx, call in unsafe_calls:
        if call.tool_id in seen_unsafe:
            continue
        seen_unsafe.add(call.tool_id)
        findings.append(
            AuditFinding(
                dimension="safety",
                severity="warning",
                tool_id=call.tool_id,
                message=(
                    f"An audit agent successfully ran '{call.tool_id}', a high-impact action "
                    "the connector doesn't gate — so an agent (or a poisoned instruction) can "
                    "trigger this irreversible operation with no confirmation."
                ),
                evidence=_evidence(seed_id, idx, call),
                suggestion=(
                    "Set `destructive: true` on this tool so clients confirm before calling it, "
                    "or `destructive: false` if it is genuinely safe to auto-run."
                ),
            )
        )

    # ── dimension scores ────────────────────────────────────────────────────
    def ratio(bad: int) -> float:
        return 1.0 - (bad / total_calls) if total_calls else 1.0

    actionable_errors = len(error_calls) - len(nonactionable_errors)
    # A skill call exercises the tools it chains, so credit them toward coverage.
    distinct_tools_used: set[str] = set()
    for _, _, c in all_calls:
        if c.tool_id in tool_ids:
            distinct_tools_used.add(c.tool_id)
        elif c.tool_id in skill_step_tools:
            distinct_tools_used |= skill_step_tools[c.tool_id] & tool_ids
    coverage = len(distinct_tools_used) / len(tool_ids) if tool_ids else 1.0

    dimension_scores = [
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
                f"oversized result; ~{total_tokens:,} tokens total."
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
        DimensionScore(
            dimension="safety",
            score=_score(ratio(len(unsafe_calls))),
            justification=(
                f"{len(seen_unsafe)} ungated high-impact tool(s) were executed by the audit."
                if unsafe_calls
                else "No ungated high-impact action was executed."
            ),
        ),
    ]

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
