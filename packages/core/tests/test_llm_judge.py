"""Tests for the LLM-judge contract (prompt builder + deterministic merge).

The LLM never runs inside Elliot — these tests exercise the pure prompt
assembly and the merge of an agent-submitted judgment with the deterministic
audit report.
"""

from __future__ import annotations

import pytest

from elliot_core.audit import (
    LLM_JUDGE_DIMENSIONS,
    build_llm_judge_prompt,
    judge_audit,
    merge_llm_judgment,
)
from elliot_core.audit.llm_judge import LlmDimensionRating, LlmJudgeFinding, LlmJudgment
from elliot_core.audit.models import AuditToolCall, AuditTranscript
from elliot_core.types import ConnectorConfig


def _connector() -> ConnectorConfig:
    return ConnectorConfig(
        name="Acme",
        slug="acme",
        version="1.0.0",
        sources=[],
        tools=[
            {
                "id": "list_customers",
                "name": "List Customers",
                "description": "Return customers filtered by plan",
                "category": "READ",
                "sql": "SELECT id, plan FROM customers LIMIT 20",
                "parameters": [],
            }
        ],  # type: ignore[arg-type]
    )


def _transcript(*, completed: bool = True) -> AuditTranscript:
    return AuditTranscript(
        seed_id="seed-1",
        task="List the pro customers",
        task_completed=completed,
        summary="Listed customers via list_customers",
        calls=[AuditToolCall(tool_id="list_customers", arguments={"plan": "pro"}, ok=True)],
    )


# ── prompt builder ───────────────────────────────────────────────────────────


def test_build_prompt_includes_dimensions_and_material() -> None:
    prompt = build_llm_judge_prompt([_transcript()], _connector())
    assert prompt["dimensions"] == LLM_JUDGE_DIMENSIONS
    tools = prompt["tools"]
    assert isinstance(tools, list) and tools[0]["id"] == "list_customers"
    transcripts = prompt["transcripts"]
    assert isinstance(transcripts, list) and transcripts[0]["seed_id"] == "seed-1"
    # The submit shape teaches the agent what to send back.
    assert "ratings" in prompt["submit_shape"]


def test_build_prompt_is_pure_no_model_field() -> None:
    # The brief must not claim a model — Elliot is not the judge.
    prompt = build_llm_judge_prompt([], _connector())
    assert prompt["transcripts"] == []
    assert "elliot_submit_llm_judgment" in prompt["instructions"]


# ── merge ────────────────────────────────────────────────────────────────────


def test_merge_appends_llm_ratings_with_provenance() -> None:
    report = judge_audit([_transcript()], _connector())
    judgment = LlmJudgment(
        model="claude-test",
        ratings=[LlmDimensionRating(dimension="description_clarity", score=9, rationale="Clear.")],
    )
    combined = merge_llm_judgment(report, judgment)

    assert combined.dimension_sources["description_clarity"] == "llm"
    # Deterministic dimensions are preserved and tagged.
    assert combined.dimension_sources["task_completion"] == "deterministic"
    clarity = next(d for d in combined.dimension_scores if d.dimension == "description_clarity")
    assert clarity.score == 9


def test_merge_llm_error_finding_fails_a_passing_report() -> None:
    report = judge_audit([_transcript()], _connector())
    assert report.passed is True  # deterministic judge is happy

    judgment = LlmJudgment(
        model="claude-test",
        findings=[
            LlmJudgeFinding(
                tool_id="list_customers",
                severity="error",
                message="Description does not say what 'plan' accepts.",
                suggestion="Enumerate the valid plans.",
            )
        ],
    )
    combined = merge_llm_judgment(report, judgment)

    assert combined.passed is False
    assert any(f.dimension == "llm_judge" for f in combined.findings)
    assert "claude-test" in combined.summary


def test_merge_warning_finding_keeps_pass() -> None:
    report = judge_audit([_transcript()], _connector())
    judgment = LlmJudgment(
        model="m",
        findings=[LlmJudgeFinding(severity="warning", message="minor", suggestion="tweak")],
    )
    combined = merge_llm_judgment(report, judgment)
    assert combined.passed is True


def test_rating_score_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        LlmDimensionRating(dimension="x", score=11)
