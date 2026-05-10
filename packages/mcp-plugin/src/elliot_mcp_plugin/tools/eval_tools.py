"""Eval and quality tools for the Elliot MCP plugin."""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.eval.models import EvalCase, EvalSuite
from elliot_core.eval.quality import analyze_connector_quality
from elliot_core.eval.runner import load_results, run_eval_suite, save_result
from elliot_core.tools.executor import ToolExecutor
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

EVAL_DIR = os.environ.get("ELLIOT_EVAL_DIR", ".elliot/eval")
EVAL_RESULTS_DIR = os.environ.get("ELLIOT_EVAL_RESULTS_DIR", ".elliot/eval-results")


def register_eval_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    async def elliot_run_eval(suite_id: str) -> dict:  # type: ignore[type-arg]
        """Run a named eval suite and return the scored EvalRunResult."""
        try:
            log.info("eval.run.start", suite_id=suite_id)
            suite_path = Path(EVAL_DIR) / f"{suite_id}.json"
            if not suite_path.exists():
                raise ElliotError("NOT_FOUND", f"Eval suite not found: {suite_id}")

            raw = json.loads(suite_path.read_text(encoding="utf-8"))
            cases = [EvalCase(**c) for c in raw.get("cases", [])]
            suite = EvalSuite(id=raw["id"], name=raw.get("name", suite_id), cases=cases)

            if session.connector is None:
                raise ElliotError("NO_CONNECTOR", "No connector loaded in session")

            executor = ToolExecutor(session.connector)
            result = await run_eval_suite(suite, executor, session.connector)
            save_result(result, Path(EVAL_RESULTS_DIR))

            log.info("eval.run.complete", suite_id=suite_id, score=result.score)
            return dataclasses.asdict(result)
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("eval.run.failed", suite_id=suite_id, error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_quality_scan() -> dict:  # type: ignore[type-arg]
        """Run a quality analysis on the current connector and return per-tool scores."""
        try:
            log.info("quality.scan.start")
            if session.connector is None:
                raise ElliotError("NO_CONNECTOR", "No connector loaded in session")

            result = analyze_connector_quality(session.connector)

            prev_results = load_results(Path(EVAL_RESULTS_DIR))
            last_score: float | None = prev_results[0].score if prev_results else None

            log.info("quality.scan.complete", overall=result.overall_score)
            return {
                "overall_score": result.overall_score,
                "error_count": result.error_count,
                "warning_count": result.warning_count,
                "last_eval_score": last_score,
                "tool_scores": [
                    {
                        "tool_id": ts.tool_id,
                        "score": ts.score,
                        "issues": [dataclasses.asdict(i) for i in ts.issues],
                    }
                    for ts in result.tool_scores
                ],
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("quality.scan.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
