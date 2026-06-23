"""LLM-as-judge *contract* — the LLM runs in the user's agent, never in Elliot.

Elliot stays deterministic. It does two things here, both pure (no model call,
no network):

1. :func:`build_llm_judge_prompt` assembles the rubric plus the exact transcript
   material the *user's agent* should grade. The agent is the LLM judge; Elliot
   only hands it a well-formed brief.
2. :func:`merge_llm_judgment` folds the structured judgment the agent submits
   back together with the deterministic :class:`AuditReport`, tracking which
   signal came from the deterministic judge and which from the LLM judge.

This mirrors the seed → transcript → judge audit flow: the thinking happens in
the agent, the bookkeeping and scoring contract happen deterministically in
Elliot so results stay reproducible and unit-testable.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from elliot_core.audit.models import (
    AuditFinding,
    AuditReport,
    AuditTranscript,
    DimensionScore,
    Severity,
)
from elliot_core.types.connector import ConnectorConfig

log = structlog.get_logger(__name__)

# Qualitative dimensions a deterministic judge cannot score — they need a model
# to read the descriptions and transcripts and form a judgement. These are the
# dimensions the user's agent grades; the deterministic judge owns the
# structural ones (error rates, token sizes, completion).
LLM_JUDGE_DIMENSIONS: list[dict[str, str]] = [
    {
        "id": "description_clarity",
        "prompt": (
            "Were the tool descriptions clear enough to pick the right tool and "
            "pass the right arguments without guessing?"
        ),
    },
    {
        "id": "tool_discoverability",
        "prompt": (
            "Could you tell the tools apart? Note any two that looked "
            "interchangeable or any task with no obvious tool."
        ),
    },
    {
        "id": "result_usefulness",
        "prompt": (
            "Did the results contain the fields the task needed, at a size that "
            "was easy to reason over?"
        ),
    },
    {
        "id": "error_recovery",
        "prompt": (
            "When a call failed, did the error message make the next step "
            "obvious, or did you have to guess?"
        ),
    },
    {
        "id": "overall_agent_experience",
        "prompt": ("Overall, how confidently could an agent use this connector to do real work?"),
    },
]


class LlmDimensionRating(BaseModel):
    """One 1-10 rating the user's agent assigns to an LLM-judge dimension."""

    dimension: str
    score: float = Field(ge=1.0, le=10.0)
    rationale: str = ""


class LlmJudgeFinding(BaseModel):
    """A qualitative problem the LLM judge surfaced, with a fix suggestion."""

    tool_id: str | None = None
    severity: Severity = "warning"
    message: str
    suggestion: str = ""


class LlmJudgment(BaseModel):
    """The structured judgement the user's agent submits after grading.

    ``model`` records which model the agent used, for provenance — Elliot does
    not call it, it only stores what the agent reports.
    """

    model: str = ""
    ratings: list[LlmDimensionRating] = []
    findings: list[LlmJudgeFinding] = []
    summary: str = ""


class CombinedAuditReport(BaseModel):
    """Deterministic + LLM judgement folded into one report.

    Every dimension score and finding is tagged by ``source`` (``deterministic``
    or ``llm``) so the UI can show who said what.
    """

    connector_slug: str
    deterministic: AuditReport
    llm_model: str = ""
    dimension_scores: list[DimensionScore] = []
    dimension_sources: dict[str, str] = {}
    findings: list[AuditFinding] = []
    passed: bool = False
    summary: str = ""


def build_llm_judge_prompt(
    transcripts: list[AuditTranscript],
    config: ConnectorConfig,
) -> dict[str, object]:
    """Assemble the brief the user's agent grades. Pure — no model call.

    Returns the rubric (the LLM-judge dimensions), a compact view of the tools
    and transcripts to grade, and the JSON shape the agent must submit back via
    ``elliot_submit_llm_judgment``.
    """
    tools_view = [
        {
            "id": t.id,
            "category": t.category,
            "description": t.description,
            "parameters": [{"name": p.name, "description": p.description} for p in t.parameters],
        }
        for t in config.tools
    ]
    transcripts_view = [
        {
            "seed_id": tr.seed_id,
            "task": tr.task,
            "task_completed": tr.task_completed,
            "summary": tr.summary,
            "calls": [
                {
                    "tool_id": c.tool_id,
                    "arguments": c.arguments,
                    "ok": c.ok,
                    "error_code": c.error_code,
                    "error_message": c.error_message,
                    "note": c.note,
                }
                for c in tr.calls
            ],
        }
        for tr in transcripts
    ]
    log.info(
        "audit.llm_judge.prompt_built",
        slug=config.slug,
        tools=len(tools_view),
        transcripts=len(transcripts_view),
    )
    return {
        "instructions": (
            "You are the LLM judge. Read the connector's tools and the audit "
            "transcripts below, then rate each dimension from 1 (poor) to 10 "
            "(excellent) with a one-sentence rationale, and list any qualitative "
            "findings with a concrete fix suggestion. Submit your judgement back "
            "with elliot_submit_llm_judgment."
        ),
        "dimensions": LLM_JUDGE_DIMENSIONS,
        "tools": tools_view,
        "transcripts": transcripts_view,
        "submit_shape": {
            "model": "<the model id you, the judge, are running as>",
            "ratings": [{"dimension": "description_clarity", "score": 8, "rationale": "..."}],
            "findings": [
                {
                    "tool_id": "list_customers",
                    "severity": "warning",
                    "message": "...",
                    "suggestion": "...",
                }
            ],
            "summary": "<one-paragraph overall judgement>",
        },
    }


def merge_llm_judgment(report: AuditReport, judgment: LlmJudgment) -> CombinedAuditReport:
    """Fold an agent's ``judgment`` into the deterministic ``report``. Pure.

    The deterministic dimension scores are kept as-is; the LLM ratings are added
    alongside them (never overwriting). ``passed`` requires both that the
    deterministic report passed and that no LLM finding is error-severity, so an
    LLM judge can fail a connector the structural checks missed.
    """
    dimension_scores: list[DimensionScore] = list(report.dimension_scores)
    dimension_sources: dict[str, str] = {
        d.dimension: "deterministic" for d in report.dimension_scores
    }

    for rating in judgment.ratings:
        dimension_scores.append(
            DimensionScore(
                dimension=rating.dimension,
                score=rating.score,
                justification=rating.rationale or "LLM judge rating.",
            )
        )
        dimension_sources[rating.dimension] = "llm"

    findings: list[AuditFinding] = list(report.findings)
    for f in judgment.findings:
        findings.append(
            AuditFinding(
                dimension="llm_judge",
                severity=f.severity,
                tool_id=f.tool_id,
                message=f.message,
                evidence="LLM judge (user agent)",
                suggestion=f.suggestion,
            )
        )

    llm_error_findings = sum(1 for f in judgment.findings if f.severity == "error")
    passed = report.passed and llm_error_findings == 0
    summary = (
        f"{'PASSED' if passed else 'NEEDS WORK'} — deterministic: {report.summary} "
        f"LLM judge ({judgment.model or 'unspecified'}): "
        f"{len(judgment.findings)} finding(s), {llm_error_findings} blocking."
    )

    log.info(
        "audit.llm_judge.merged",
        slug=report.connector_slug,
        passed=passed,
        llm_findings=len(judgment.findings),
        llm_model=judgment.model,
    )
    return CombinedAuditReport(
        connector_slug=report.connector_slug,
        deterministic=report,
        llm_model=judgment.model,
        dimension_scores=dimension_scores,
        dimension_sources=dimension_sources,
        findings=findings,
        passed=passed,
        summary=summary,
    )
