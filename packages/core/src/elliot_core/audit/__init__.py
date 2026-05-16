"""Petri-style agentic auditing for Elliot connectors.

The audit subsystem turns connector quality from a static pass/fail into a
transcript: realistic agent tasks (`AuditSeed`) are attempted against the
connector by sub-agents, every tool call is recorded (`AuditTranscript`), and a
deterministic judge scores the transcripts on graded dimensions and emits
findings that cite the exact failing call (`AuditReport`).
"""

from __future__ import annotations

from elliot_core.audit.judge import judge_audit
from elliot_core.audit.models import (
    AuditFinding,
    AuditReport,
    AuditSeed,
    AuditToolCall,
    AuditTranscript,
    DimensionScore,
    ProductIntent,
)
from elliot_core.audit.seeds import generate_audit_seeds
from elliot_core.audit.store import (
    audit_rubric,
    load_audit_reports,
    save_audit_report,
)

__all__ = [
    "AuditFinding",
    "AuditReport",
    "AuditSeed",
    "AuditToolCall",
    "AuditTranscript",
    "DimensionScore",
    "ProductIntent",
    "audit_rubric",
    "generate_audit_seeds",
    "judge_audit",
    "load_audit_reports",
    "save_audit_report",
]
