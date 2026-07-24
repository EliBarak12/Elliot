"""Persistence for audit reports and the audit rubric handed to sub-agents."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from elliot_core.audit.models import AuditReport

log = structlog.get_logger(__name__)


def save_audit_report(report: AuditReport, results_dir: Path) -> Path:
    """Write ``report`` to ``results_dir`` as a timestamped JSON file."""
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.run_at.replace(":", "-").replace(".", "-")
    path = results_dir / f"{report.connector_slug}-{stamp}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)
    log.info("audit.report.saved", path=str(path), passed=report.passed)
    return path


def load_audit_reports(results_dir: Path) -> list[AuditReport]:
    """Load every saved audit report, newest first. Corrupt files are skipped."""
    if not results_dir.is_dir():
        return []
    reports: list[AuditReport] = []
    for path in results_dir.glob("*.json"):
        try:
            reports.append(AuditReport.model_validate_json(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("audit.report.skip_corrupt", path=str(path), error=str(exc))
    reports.sort(key=lambda r: r.run_at, reverse=True)
    return reports


def audit_rubric() -> str:
    """The judging rubric — handed to audit sub-agents so they know what matters.

    Deterministic scoring lives in :func:`elliot_core.audit.judge.judge_audit`;
    this text tells the sub-agents which signals to record in their transcript.
    """
    return (
        "AUDIT RUBRIC — record these signals in your transcript:\n"
        "- task_completion: did you finish the task using only connector tools?\n"
        "- tool_reliability: which calls errored, and with what code/message?\n"
        "- error_actionability: did each error tell you the next step to take?\n"
        "- token_efficiency: flag any result that felt far larger than needed.\n"
        "- schema_clarity: note any parameter whose name/type/meaning was unclear.\n"
        "- tool_selection: note if two tools looked interchangeable, or a tool "
        "you needed did not exist.\n"
        "- safety: try to trigger an irreversible or high-impact action "
        "(cancel/refund/suspend/delete/…). Log whether it ran with NO "
        "confirmation step — an ungated danger zone is a finding.\n"
        "For every tool call, log: tool_id, arguments, ok, error_code, "
        "error_message, result_row_count, result_token_estimate, and a short "
        "note when something was confusing."
    )
