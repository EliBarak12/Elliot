"""Audit tools — run a Petri-style parallel audit of a built connector.

The host agent drives the audit: it calls ``elliot_generate_audit_seeds``,
spawns one sub-agent per seed to exercise the connector, submits each
sub-agent's transcript with ``elliot_submit_audit_transcript``, then calls
``elliot_judge_audit`` to score the run and get actionable findings.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import structlog
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from elliot_core.audit import (
    audit_rubric,
    generate_audit_seeds,
    judge_audit,
    save_audit_report,
)
from elliot_core.audit.models import AuditTranscript
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

# Explicit override for where judged audit reports are written. When unset we
# fall back to the session's workspace dir (ELLIOT_WORKSPACE/.elliot/...) at
# call time — NOT a cwd-relative ".elliot", which on the hosted builder is a
# read-only directory and made elliot_judge_audit fail with
# "[Errno 13] Permission denied: '.elliot'" (audit B1/H9).
_AUDIT_RESULTS_DIR_ENV = os.environ.get("ELLIOT_AUDIT_RESULTS_DIR")


def _audit_results_dir(session: ElliotSession) -> Path:
    if _AUDIT_RESULTS_DIR_ENV:
        return Path(_AUDIT_RESULTS_DIR_ENV)
    return session.workspace._dir / "audit-results"


_NO_CONNECTOR = ElliotError(
    "NO_CONNECTOR",
    "No connector built yet — call elliot_build_connector first.",
)


def register_audit_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_generate_audit_seeds(
        count: Annotated[int, Field(json_schema_extra={"minimum": 1, "maximum": 20})] = 5,
    ) -> dict:  # type: ignore[type-arg]
        """Generate realistic agent-task seeds for auditing the built connector.

        Returns up to ``count`` seeds plus the rubric and the instructions for
        spawning the audit sub-agents. Each seed should be handed to one
        sub-agent that exercises the connector tools (via elliot_preview_tool)
        and reports a transcript.
        """
        try:
            if session.connector is None:
                raise _NO_CONNECTOR
            seeds = generate_audit_seeds(
                session.connector, session.product_intent, limit=max(1, count)
            )
            log.info("audit.seeds.requested", count=len(seeds))
            return {
                "seed_count": len(seeds),
                "seeds": [s.model_dump() for s in seeds],
                "rubric": audit_rubric(),
                "instructions": (
                    f"Spawn {len(seeds)} parallel sub-agents, one per seed. Give "
                    "each sub-agent ONLY the connector's tools (exercised through "
                    "elliot_preview_tool against the sandbox data). Each sub-agent "
                    "attempts its seed task, records every tool call per the "
                    "rubric, and you submit its transcript with "
                    "elliot_submit_audit_transcript. When all transcripts are in, "
                    "call elliot_judge_audit."
                ),
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("audit.seeds.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_submit_audit_transcript(
        transcript_json: dict | str,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Submit one audit sub-agent's transcript.

        ``transcript_json`` is an AuditTranscript: pass it as an object
        (preferred) or a JSON string. Fields: seed_id, task, agent_label,
        task_completed, summary, and a `calls` list where each call has
        tool_id, arguments, ok, error_code, error_message, result_row_count,
        result_token_estimate, note.
        """
        try:
            data = (
                json.loads(transcript_json) if isinstance(transcript_json, str) else transcript_json
            )
            transcript = AuditTranscript.model_validate(data)
            session.audit_transcripts.append(transcript)
            session.save()
            log.info(
                "audit.transcript.submitted",
                seed_id=transcript.seed_id,
                calls=len(transcript.calls),
                total=len(session.audit_transcripts),
            )
            return {
                "status": "submitted",
                "seed_id": transcript.seed_id,
                "calls_recorded": len(transcript.calls),
                "transcripts_total": len(session.audit_transcripts),
            }
        except json.JSONDecodeError as exc:
            return to_mcp_error_content(ElliotError("INVALID_JSON", f"Invalid JSON: {exc}"))
        except ValueError as exc:
            return to_mcp_error_content(
                ElliotError("INVALID_TRANSCRIPT", f"Transcript did not validate: {exc}")
            )
        except Exception as exc:
            log.error("audit.transcript.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_audit_transcripts() -> dict:  # type: ignore[type-arg]
        """List the audit transcripts submitted so far this session."""
        return {
            "count": len(session.audit_transcripts),
            "transcripts": [
                {
                    "seed_id": t.seed_id,
                    "agent_label": t.agent_label,
                    "calls": len(t.calls),
                    "task_completed": t.task_completed,
                }
                for t in session.audit_transcripts
            ],
        }

    @mcp.tool()
    def elliot_clear_audit_transcripts() -> dict:  # type: ignore[type-arg]
        """Discard all submitted audit transcripts (start a fresh audit run)."""
        cleared = len(session.audit_transcripts)
        session.audit_transcripts = []
        session.save()
        log.info("audit.transcripts.cleared", cleared=cleared)
        return {"status": "cleared", "cleared": cleared}

    @mcp.tool()
    def elliot_judge_audit() -> dict:  # type: ignore[type-arg]
        """Judge all submitted transcripts and return a scored audit report.

        Scores graded 1-10 dimensions and emits findings that cite the exact
        failing call. Fix the error-severity findings, rebuild, then re-run the
        audit until it passes.
        """
        try:
            if session.connector is None:
                raise _NO_CONNECTOR
            if not session.audit_transcripts:
                raise ElliotError(
                    "NO_TRANSCRIPTS",
                    "No transcripts submitted — run the audit sub-agents and "
                    "submit their transcripts first.",
                )
            report = judge_audit(session.audit_transcripts, session.connector)
            saved = save_audit_report(report, _audit_results_dir(session))
            log.info("audit.judged", passed=report.passed, path=str(saved))
            result = report.model_dump()
            result["report_path"] = str(saved)
            return result
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("audit.judge.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
