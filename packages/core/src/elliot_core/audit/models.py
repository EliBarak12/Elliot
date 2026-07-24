"""Data models for the connector audit subsystem."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["error", "warning", "info"]


class ProductIntent(BaseModel):
    """What the user told Elliot about how agents should use their product.

    Captured during the onboarding interview — before any tool is designed —
    so tool design and auditing are driven by intent, not guesswork.
    """

    agent_consumers: list[str] = []
    """Who the agents are (e.g. "customer-support bot", "internal data copilot")."""

    jobs_to_be_done: list[str] = []
    """Concrete tasks agents should accomplish. These become audit seeds."""

    exposed_operations: list[str] = []
    """Operations the user explicitly wants exposed as tools."""

    destructive_operations: list[str] = []
    """Operations that mutate or are irreversible — need a confirmation gate."""

    sensitive_fields: list[str] = []
    """Field names that must never appear in a tool result (PII, secrets)."""

    scale_notes: str = ""
    """Free-text on expected result volume / data size."""

    notes: str = ""
    """Anything else the user said that shapes the connector."""


class AuditSeed(BaseModel):
    """A realistic agent task used to exercise a connector during an audit."""

    id: str
    task: str
    job: str = ""
    suggested_tools: list[str] = []


class AuditToolCall(BaseModel):
    """One tool invocation recorded by an audit sub-agent."""

    tool_id: str
    arguments: dict[str, Any] = {}
    ok: bool = True
    error_code: str | None = None
    error_message: str | None = None
    result_row_count: int | None = None
    result_token_estimate: int | None = None
    note: str = ""
    """The sub-agent's observation — e.g. "retried after a confusing schema"."""
    is_skill: bool = False
    """True when ``tool_id`` names a skill the agent invoked as one call (rather
    than a plain tool), so the transcript records that the workflow was exercised
    end-to-end."""


class AuditTranscript(BaseModel):
    """One audit sub-agent's full attempt at a single seed task."""

    seed_id: str
    task: str
    agent_label: str = ""
    calls: list[AuditToolCall] = []
    task_completed: bool = False
    summary: str = ""
    build_id: str = ""
    """Id of the connector build this transcript was recorded against.

    Stamped at submit time so the judge can score only the transcripts for the
    CURRENT build — a re-judge after fixing tools must not be dragged down by
    stale prior-build runs whose failures are already fixed. Empty for
    transcripts submitted before build-scoping existed."""


class DimensionScore(BaseModel):
    """A graded 1-10 score on one audit dimension (higher = better)."""

    dimension: str
    score: float
    justification: str


class AuditFinding(BaseModel):
    """A single actionable problem surfaced by the judge, citing its evidence."""

    dimension: str
    severity: Severity
    tool_id: str | None
    message: str
    evidence: str
    suggestion: str


class AuditReport(BaseModel):
    """The judged result of an audit run across every transcript."""

    connector_slug: str
    run_at: str
    seed_count: int
    transcript_count: int
    task_success_rate: float
    total_tool_calls: int
    error_call_count: int
    total_token_estimate: int
    dimension_scores: list[DimensionScore] = []
    findings: list[AuditFinding] = []
    passed: bool = False
    summary: str = ""
