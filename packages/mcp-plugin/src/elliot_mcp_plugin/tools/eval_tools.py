"""Eval and quality tools for the Elliot MCP plugin."""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.eval.models import EvalCase, EvalSuite
from elliot_core.eval.quality import BEST_PRACTICES, analyze_connector_quality
from elliot_core.eval.runner import load_results, run_eval_suite, save_result
from elliot_core.eval_runner import EvalRunner
from elliot_core.eval_types import EvalCase as YamlEvalCase
from elliot_core.eval_types import EvalSuite as YamlEvalSuite
from elliot_core.eval_types import load_eval_suite as load_yaml_eval_suite
from elliot_core.mcp_compat import FastMCP
from elliot_core.tools.executor import ToolExecutor
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

EVAL_DIR = os.environ.get("ELLIOT_EVAL_DIR", ".elliot/eval")
EVAL_RESULTS_DIR = os.environ.get("ELLIOT_EVAL_RESULTS_DIR", ".elliot/eval-results")


def _resolve_suite_path(path: str | None, suite_id: str | None, session: ElliotSession) -> Path:
    """Pick the eval-suite file from either an explicit path or a suite_id lookup.

    Lookup order for ``suite_id`` (kept for backward compatibility):
      1. ``<EVAL_DIR>/<suite_id>.yaml``
      2. ``<EVAL_DIR>/<suite_id>.yml``
      3. ``<EVAL_DIR>/<suite_id>.json``
    """
    if path:
        # Resolve relative paths against the workspace project root so an agent
        # can pass ``connectors/foo.eval.yaml`` without needing the absolute path.
        p = Path(path)
        if not p.is_absolute():
            project_root = Path(session.workspace._dir).resolve().parent
            p = project_root / p
        if not p.exists():
            raise ElliotError("NOT_FOUND", f"Eval suite not found: {p}")
        return p
    if suite_id:
        for suffix in (".yaml", ".yml", ".json"):
            candidate = Path(EVAL_DIR) / f"{suite_id}{suffix}"
            if candidate.exists():
                return candidate
        raise ElliotError("NOT_FOUND", f"Eval suite not found: {suite_id}")
    raise ElliotError(
        "VALIDATION_ERROR",
        "Pass either `path` (to a .eval.yaml / .json file) or `suite_id`.",
    )


def _shape_yaml_result(suite: YamlEvalSuite, case_results: list[Any], fmt: str) -> dict[str, Any]:
    """Score EvalRunner CaseResults into the MCP response shape."""
    passed = sum(1 for r in case_results if r.passed)
    failed = len(case_results) - passed
    score = round(passed / len(case_results) * 100, 1) if case_results else 100.0
    return {
        "suite_id": suite.connector,
        "suite_name": suite.name,
        "format": fmt,
        "run_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "score": score,
        "passed": passed,
        "failed": failed,
        "cases": [dataclasses.asdict(c) for c in case_results],
    }


async def _run_yaml_suite(path: Path, session: ElliotSession) -> dict[str, Any]:
    """Run a rich .eval.yaml suite via EvalRunner and shape the result for MCP."""
    suite = load_yaml_eval_suite(path)
    secrets = session.workspace.load_secrets()
    runner = EvalRunner(session.connector, secrets)  # type: ignore[arg-type]
    case_results = await runner.run_suite(suite)
    return _shape_yaml_result(suite, case_results, "yaml")


async def _run_inline_suite(
    cases: list[dict[str, Any]], session: ElliotSession, name: str
) -> dict[str, Any]:
    """Run cases the agent passes inline — no file, no shared eval dir.

    This is the cloud path for lint -> eval -> publish: the agent authors test
    cases and runs them against the built connector in one call, with results
    scoped to its own session (never a host-shared directory)."""
    if not cases:
        raise ElliotError("VALIDATION_ERROR", "`cases` must be a non-empty list of eval cases.")
    try:
        suite = YamlEvalSuite(
            name=name or "inline",
            connector=session.connector.slug,  # type: ignore[union-attr]
            cases=[YamlEvalCase.model_validate(c) for c in cases],
        )
    except ValidationError as exc:
        raise ElliotError(
            "VALIDATION_ERROR",
            "Invalid eval case. Each case needs `tool_id` and optional `arguments` + "
            f"`expect` (no_error/min_rows/fields_present/max_token_estimate…). {exc}",
        ) from exc
    secrets = session.workspace.load_secrets()
    runner = EvalRunner(session.connector, secrets)  # type: ignore[arg-type]
    case_results = await runner.run_suite(suite)
    return _shape_yaml_result(suite, case_results, "inline")


async def _run_json_suite(path: Path, session: ElliotSession) -> dict[str, Any]:
    """Run a legacy JSON suite via the dataclass runner."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    valid_fields = {f.name for f in dataclasses.fields(EvalCase)}
    cases = [
        EvalCase(**{k: v for k, v in c.items() if k in valid_fields}) for c in raw.get("cases", [])
    ]
    suite = EvalSuite(id=raw["id"], name=raw.get("name", raw["id"]), cases=cases)

    executor = ToolExecutor(session.connector)  # type: ignore[arg-type]
    result = await run_eval_suite(suite, executor, session.connector)  # type: ignore[arg-type]
    save_result(result, Path(EVAL_RESULTS_DIR))
    return dataclasses.asdict(result)


def register_eval_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    async def elliot_run_eval(
        suite_id: str | None = None,
        path: str | None = None,
        cases: list[dict[str, Any]] | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Run an eval suite against the built connector and return scored results.

        Three ways to supply the cases:

        - ``cases`` — a list of eval cases passed INLINE. This is the path that
          works on Elliot Cloud (no file needed): the agent authors test cases
          and runs them in one call, so lint -> eval -> publish completes without
          touching a host directory. Each case is
          ``{"id": "...", "tool_id": "...", "arguments": {...},
          "expect": {"no_error": true, "min_rows": 1, "fields_present": ["id"],
          "max_token_estimate": 800}}`` — only ``tool_id`` is required.
        - ``path`` — a ``.eval.yaml`` / ``.eval.yml`` / ``.json`` file (absolute
          or relative to the project root).
        - ``suite_id`` — looked up under ``<EVAL_DIR>/<suite_id>.{yaml,yml,json}``
          (default ``.elliot/eval``); file-based, mainly for local runs.

        The rich ``expect`` shape (no_error, min_rows, fields_present,
        max_token_estimate, all_rows_match, error_code) is documented in
        ``connectors/my-saas.eval.yaml``.
        """
        try:
            if session.connector is None:
                raise ElliotError("NO_CONNECTOR", "No connector loaded in session")
            if cases is not None:
                result = await _run_inline_suite(cases, session, name=suite_id or "inline")
                log.info("eval.run.complete", format="inline", score=result["score"])
                return result
            suite_path = _resolve_suite_path(path, suite_id, session)
            log.info("eval.run.start", path=str(suite_path))
            if suite_path.suffix.lower() in (".yaml", ".yml"):
                result = await _run_yaml_suite(suite_path, session)
            else:
                result = await _run_json_suite(suite_path, session)
            log.info("eval.run.complete", path=str(suite_path), score=result["score"])
            return result
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("eval.run.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_eval_suites() -> dict:  # type: ignore[type-arg]
        """List discoverable eval suites — the ``suite_id`` values elliot_run_eval accepts.

        Scans ``<EVAL_DIR>`` (default ``.elliot/eval``) for ``.yaml`` / ``.yml`` /
        ``.json`` files; each suite_id is the filename stem. Lets a UI populate a
        suite dropdown instead of asking the user to guess a name.
        """
        try:
            eval_dir = Path(EVAL_DIR)
            suites: list[dict[str, str]] = []
            if eval_dir.is_dir():
                for f in sorted(eval_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".yaml", ".yml", ".json"):
                        suites.append(
                            {
                                "suite_id": f.stem,
                                "path": str(f),
                                "format": f.suffix.lstrip(".").lower(),
                            }
                        )
            return {"suites": suites, "count": len(suites), "eval_dir": str(eval_dir)}
        except Exception as exc:
            log.error("eval.list_suites.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_quality_scan() -> dict:  # type: ignore[type-arg]
        """Run a quality analysis on the current connector and return per-tool scores.

        Each issue is tagged with the ``principle`` from Anthropic's mcp-builder
        skill that it enforces, and the response includes the ``best_practices``
        catalog so the Evaluation page can group results by best-practice area.
        """
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
                "best_practices": BEST_PRACTICES,
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
