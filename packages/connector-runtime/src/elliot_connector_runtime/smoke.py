"""Publish-time smoke test: prove a connector actually serves before it ships.

A connector can lint clean and still fail every call at runtime — a source
that 404s live, SQL against a column the flattener never produced, a secret
that resolves to the wrong value. The static linter cannot see any of that,
so the smoke test does what an agent would do on first connect:

1. **Registration smoke** — build a fresh runtime server for the config (the
   same ``create_runtime_server`` the real runtime uses, with observability
   disabled) and run ``tools/list``, verifying every connector tool registered
   and serializes to an MCP tool schema.
2. **Execute smoke** — call each READ tool exactly the way an agent naturally
   does on first touch: required parameters filled from their declared default
   or first enum value, optional parameters omitted. WRITE/ACTION tools are
   never executed (they mutate upstream systems); READ tools whose required
   parameters cannot be auto-filled are reported as skipped, not failed.

The execute smoke performs live I/O against the connector's sources — that is
the point: it proves the served path end-to-end. Callers that must not touch
the network can pass ``execute=False`` for the registration smoke alone.

The report never raises: every failure mode lands in ``SmokeReport`` so the
caller (e.g. a cloud publish gate) can decide what blocks and what warns.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from elliot_core.types import ConnectorConfig, ToolDefinition

from .executor import ToolExecutor

log = structlog.get_logger(__name__)

# Generous enough for a cold materialization of a real source, small enough
# that a hung upstream cannot stall a publish indefinitely.
DEFAULT_TOOL_TIMEOUT_SECONDS = 20.0

# Error strings are bounded so a report stays a report — the full trace
# belongs in the log, not in an API response (and never row data).
_MAX_ERROR_CHARS = 300

SMOKE_TIMEOUT_CODE = "SMOKE_TIMEOUT"


class ToolSmokeResult(BaseModel):
    tool_id: str
    status: Literal["passed", "failed", "skipped"]
    # Failure message or skip reason; never carries row data.
    reason: str | None = None
    # Structured code when the failure was an ElliotError (TABLE_NOT_FOUND,
    # UPSTREAM_FETCH_FAILED, ...), SMOKE_TIMEOUT on timeout.
    error_code: str | None = None
    duration_ms: float = 0.0
    rows: int | None = None


class SmokeReport(BaseModel):
    passed: bool
    # Tool names the built server actually lists (includes runtime built-ins).
    listed_tools: list[str] = []
    # Estimated token cost of the serialized tools/list response — what merely
    # CONNECTING this connector charges an agent's context window before any
    # call is made. The ecosystem's #1 complaint about MCP servers, measured.
    context_tokens: int = 0
    # Connector tools that failed to appear in tools/list.
    missing_tools: list[str] = []
    # The server could not even be built / listed (bad signature, bad schema).
    registration_error: str | None = None
    tool_results: list[ToolSmokeResult] = []
    duration_ms: float = 0.0

    def failures(self) -> list[ToolSmokeResult]:
        return [r for r in self.tool_results if r.status == "failed"]

    def summary(self) -> str:
        """One line for logs and publish-gate messages."""
        if self.registration_error:
            return f"connector failed to register: {self.registration_error}"
        parts: list[str] = []
        if self.missing_tools:
            parts.append(f"missing from tools/list: {', '.join(self.missing_tools)}")
        failed = self.failures()
        if failed:
            parts.append(
                "failing tools: "
                + ", ".join(f"{r.tool_id} [{r.error_code or 'ERROR'}]" for r in failed)
            )
        if not parts:
            executed = sum(1 for r in self.tool_results if r.status == "passed")
            return f"ok ({len(self.listed_tools)} tools listed, {executed} executed)"
        return "; ".join(parts)


def smoke_arguments(tool: ToolDefinition) -> dict[str, Any] | None:
    """Arguments for the natural first call an agent makes to ``tool``.

    Required parameters are filled from their declared ``default`` or the
    first ``enum`` value — both author-declared, so the call stays within the
    tool's own contract. Optional parameters are omitted on purpose: the
    omitted-optional path is the one agents hit first and the one that has
    shipped broken (a tool whose no-arg path 404s while the with-arg path
    works). Returns ``None`` when a required parameter has neither a default
    nor an enum — such a tool needs caller-supplied values the smoke must not
    invent.
    """
    args: dict[str, Any] = {}
    for p in tool.parameters:
        if not p.required:
            continue
        if p.default is not None:
            args[p.name] = p.default
        elif p.enum:
            args[p.name] = p.enum[0]
        else:
            return None
    return args


def _first_line(text: str) -> str:
    line = next((ln for ln in str(text).splitlines() if ln.strip()), "")
    return line[:_MAX_ERROR_CHARS]


async def _build_and_list(config: ConnectorConfig, executor: ToolExecutor) -> tuple[list[str], int]:
    """Build a fresh, observability-free runtime server and list its tools.

    Returns ``(tool_names, context_tokens)`` where ``context_tokens`` estimates
    the serialized ``tools/list`` payload — the context-window cost of simply
    connecting the connector. Raises whatever registration raises — the caller
    converts it into a ``registration_error``. The server is throwaway: no
    session manager is started and nothing is written to disk.
    """
    from .server import create_runtime_server
    from .session_tracker import _estimate_tokens

    mcp = create_runtime_server(config, executor)
    tools = await mcp.list_tools()
    serialized = [t.model_dump(mode="json", exclude_none=True) for t in tools]
    return [t.name for t in tools], _estimate_tokens(serialized)


async def _execute_one(
    executor: ToolExecutor,
    tool: ToolDefinition,
    timeout_seconds: float,
) -> ToolSmokeResult:
    from elliot_core.errors import ElliotError

    args = smoke_arguments(tool)
    if tool.category != "READ":
        return ToolSmokeResult(
            tool_id=tool.id,
            status="skipped",
            reason=f"{tool.category} tool — mutating tools are never executed by the smoke test",
        )
    if args is None:
        needed = [p.name for p in tool.parameters if p.required and p.default is None]
        return ToolSmokeResult(
            tool_id=tool.id,
            status="skipped",
            reason=(
                "requires caller-supplied value(s) for required parameter(s): " + ", ".join(needed)
            ),
        )

    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(executor.execute(tool, args), timeout=timeout_seconds)
    except TimeoutError:
        return ToolSmokeResult(
            tool_id=tool.id,
            status="failed",
            reason=f"did not answer within {timeout_seconds:.0f}s",
            error_code=SMOKE_TIMEOUT_CODE,
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    except Exception as exc:
        code = exc.code if isinstance(exc, ElliotError) else "TOOL_EXECUTION_ERROR"
        return ToolSmokeResult(
            tool_id=tool.id,
            status="failed",
            reason=_first_line(str(exc)),
            error_code=code,
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    return ToolSmokeResult(
        tool_id=tool.id,
        status="passed",
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
        rows=len(result.rows),
    )


async def smoke_test_connector(
    config: ConnectorConfig,
    executor: ToolExecutor,
    *,
    execute: bool = True,
    tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> SmokeReport:
    """Run the full smoke test and return a report; never raises.

    ``executor`` should be a throwaway built for this smoke — its
    materialization cache is warmed by the run, so reusing the serving
    executor would blur what was actually proven.
    """
    t0 = time.monotonic()
    log.info("smoke.start", connector=config.slug, tools=len(config.tools), execute=execute)

    try:
        listed, context_tokens = await _build_and_list(config, executor)
    except Exception as exc:
        log.error("smoke.registration_failed", connector=config.slug, error=str(exc))
        return SmokeReport(
            passed=False,
            registration_error=_first_line(str(exc)),
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )

    listed_set = set(listed)
    # A disabled tool is deliberately absent from tools/list. Smoking it would
    # report every one as "missing from tools/list" and block the publish — the
    # gate proves what the connector *offers*, and a disabled tool offers
    # nothing.
    smokeable = [t for t in config.tools if getattr(t, "enabled", True)]
    missing = [t.id for t in smokeable if t.id not in listed_set]

    tool_results: list[ToolSmokeResult] = []
    if execute:
        for tool in smokeable:
            if tool.id in missing:
                continue
            outcome = await _execute_one(executor, tool, tool_timeout_seconds)
            tool_results.append(outcome)
            log.info(
                "smoke.tool",
                connector=config.slug,
                tool=tool.id,
                status=outcome.status,
                code=outcome.error_code,
                duration_ms=outcome.duration_ms,
            )

    report = SmokeReport(
        passed=not missing and not any(r.status == "failed" for r in tool_results),
        listed_tools=listed,
        context_tokens=context_tokens,
        missing_tools=missing,
        tool_results=tool_results,
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
    )
    log.info(
        "smoke.complete",
        connector=config.slug,
        passed=report.passed,
        summary=report.summary(),
    )
    return report
