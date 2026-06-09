"""Product-market-fit signal queries over the observation store.

Computes the three numbers the SCOPE.md evidence gates depend on:

1. Active installations / agents / days  — who is *actually* using a connector,
   on more than one day, in the last N days.
2. Sean Ellis distribution             — share of survey responses that would
   be "very disappointed" if Elliot went away.
3. Tool-call success rate              — per-tool and overall, so a connector
   author can see whether agents can use their tools cleanly.

The store already records every tool call, every session and every feedback
submission. This module just rolls those rows up into the few numbers a
maintainer should review weekly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from .observation_store import ObservationStore, _AgentFeedback

log = structlog.get_logger(__name__)


_SEAN_ELLIS_RESPONSES = ("very_disappointed", "somewhat_disappointed", "not_disappointed")
_SEAN_ELLIS_THRESHOLD = 0.40  # 40% "very disappointed" is the published bar


@dataclass(frozen=True)
class RetentionReport:
    window_days: int
    active_installations: int
    active_agents: int  # distinct (agent_client, agent_model) pairs
    active_days_median: float  # per installation
    repeat_installations: int  # installations active on >=2 distinct days
    total_sessions: int
    total_tool_calls: int
    error_rate: float  # share of tool calls that errored


@dataclass(frozen=True)
class SeanEllisReport:
    window_days: int
    responses: int
    very_disappointed: int
    somewhat_disappointed: int
    not_disappointed: int

    @property
    def very_disappointed_share(self) -> float:
        if not self.responses:
            return 0.0
        return self.very_disappointed / self.responses

    @property
    def passes_threshold(self) -> bool:
        return self.very_disappointed_share >= _SEAN_ELLIS_THRESHOLD


@dataclass(frozen=True)
class ToolSuccessRow:
    tool_id: str
    calls: int
    errors: int
    success_rate: float


def retention(store: ObservationStore, window_days: int = 14) -> RetentionReport:
    """Roll up activity over the window into a single retention snapshot.

    "Installation" is approximated as the ``agent_client_version`` field on
    ``agent_sessions``, falling back to ``agent_client`` for older rows. That
    is the most stable id we have without writing a separate handshake — a
    given Claude Code install reports the same version string across runs.
    """
    cutoff = time.time() - (window_days * 86400)

    with Session(store._engine) as db:  # noqa: SLF001 — internal use only
        rows = db.execute(
            text(
                """
                SELECT
                    COALESCE(s.agent_client_version, s.agent_client, 'unknown') AS installation,
                    s.agent_client                                              AS client,
                    s.agent_model                                               AS model,
                    DATE(s.started_at, 'unixepoch')                             AS active_day,
                    COUNT(*)                                                    AS sessions
                FROM agent_sessions s
                WHERE s.started_at >= :cutoff
                GROUP BY installation, client, model, active_day
                """
            ),
            {"cutoff": cutoff},
        ).fetchall()

        tool_rows = db.execute(
            text(
                """
                SELECT
                    COUNT(*) AS calls,
                    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
                FROM tool_calls
                WHERE ts >= :cutoff
                """
            ),
            {"cutoff": cutoff},
        ).fetchone()

    days_by_install: dict[str, set[str]] = {}
    agents: set[tuple[str | None, str | None]] = set()
    total_sessions = 0
    for r in rows:
        m = r._mapping
        days_by_install.setdefault(m["installation"], set()).add(m["active_day"])
        agents.add((m["client"], m["model"]))
        total_sessions += int(m["sessions"] or 0)

    active_installations = len(days_by_install)
    repeat = sum(1 for days in days_by_install.values() if len(days) >= 2)
    if days_by_install:
        sorted_counts = sorted(len(d) for d in days_by_install.values())
        mid = len(sorted_counts) // 2
        median = (
            sorted_counts[mid]
            if len(sorted_counts) % 2
            else (sorted_counts[mid - 1] + sorted_counts[mid]) / 2
        )
    else:
        median = 0.0

    calls = int((tool_rows._mapping["calls"] if tool_rows else 0) or 0)
    errors = int((tool_rows._mapping["errors"] if tool_rows else 0) or 0)
    error_rate = (errors / calls) if calls else 0.0

    return RetentionReport(
        window_days=window_days,
        active_installations=active_installations,
        active_agents=len(agents),
        active_days_median=float(median),
        repeat_installations=repeat,
        total_sessions=total_sessions,
        total_tool_calls=calls,
        error_rate=error_rate,
    )


def sean_ellis(store: ObservationStore, window_days: int = 30) -> SeanEllisReport:
    """Tally Sean Ellis survey responses recorded via ``elliot_pmf_signal``.

    Responses are stored in ``agent_feedback`` with a reserved ``tool_id`` of
    ``__pmf_survey`` and the user's choice in ``outcome``. This lets us reuse
    the existing feedback table — no new schema, no migration — while still
    keeping the PMF signal cleanly separable from per-tool feedback.
    """
    cutoff = time.time() - (window_days * 86400)
    counts = {choice: 0 for choice in _SEAN_ELLIS_RESPONSES}
    with Session(store._engine) as db:  # noqa: SLF001
        rows = (
            db.query(_AgentFeedback)
            .filter(_AgentFeedback.tool_id == "__pmf_survey")
            .filter(_AgentFeedback.ts >= cutoff)
            .all()
        )
    for row in rows:
        choice = (row.outcome or "").strip().lower()
        if choice in counts:
            counts[choice] += 1
    return SeanEllisReport(
        window_days=window_days,
        responses=sum(counts.values()),
        very_disappointed=counts["very_disappointed"],
        somewhat_disappointed=counts["somewhat_disappointed"],
        not_disappointed=counts["not_disappointed"],
    )


def tool_success(
    store: ObservationStore,
    window_days: int = 14,
    min_calls: int = 20,
) -> list[ToolSuccessRow]:
    """Per-tool success rate over the window, filtered to tools with enough calls.

    Tools with fewer than ``min_calls`` calls are excluded — the success rate
    of a tool that was used three times is noise, not signal.
    """
    cutoff = time.time() - (window_days * 86400)
    with Session(store._engine) as db:  # noqa: SLF001
        rows = db.execute(
            text(
                """
                SELECT
                    tool_id,
                    COUNT(*)                                          AS calls,
                    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
                FROM tool_calls
                WHERE ts >= :cutoff
                GROUP BY tool_id
                HAVING COUNT(*) >= :min_calls
                ORDER BY calls DESC
                """
            ),
            {"cutoff": cutoff, "min_calls": min_calls},
        ).fetchall()
    out: list[ToolSuccessRow] = []
    for r in rows:
        m = r._mapping
        calls = int(m["calls"] or 0)
        errors = int(m["errors"] or 0)
        success_rate = ((calls - errors) / calls) if calls else 0.0
        out.append(
            ToolSuccessRow(
                tool_id=str(m["tool_id"]),
                calls=calls,
                errors=errors,
                success_rate=success_rate,
            )
        )
    return out


def kpi_brief(store: ObservationStore, window_days: int = 14) -> dict[str, Any]:
    """One dict that bundles the three SCOPE.md evidence gates.

    Returned shape is stable so the CLI, Studio, and any downstream consumer
    (a weekly Slack post, a check in CI) read the same numbers.
    """
    r = retention(store, window_days=window_days)
    s = sean_ellis(store, window_days=max(window_days, 30))
    tools = tool_success(store, window_days=window_days)

    median_success = 0.0
    if tools:
        sorted_rates = sorted(t.success_rate for t in tools)
        mid = len(sorted_rates) // 2
        median_success = (
            sorted_rates[mid]
            if len(sorted_rates) % 2
            else (sorted_rates[mid - 1] + sorted_rates[mid]) / 2
        )

    gates = {
        "active_installations_ge_10": r.active_installations >= 10 and r.repeat_installations >= 10,
        "sean_ellis_ge_40pct": s.passes_threshold,
        "median_success_ge_90pct": bool(tools) and median_success >= 0.90,
    }

    return {
        "window_days": window_days,
        "generated_at": time.time(),
        "retention": {
            "active_installations": r.active_installations,
            "repeat_installations": r.repeat_installations,
            "active_agents": r.active_agents,
            "active_days_median": r.active_days_median,
            "total_sessions": r.total_sessions,
            "total_tool_calls": r.total_tool_calls,
            "error_rate": r.error_rate,
        },
        "sean_ellis": {
            "window_days": s.window_days,
            "responses": s.responses,
            "very_disappointed": s.very_disappointed,
            "somewhat_disappointed": s.somewhat_disappointed,
            "not_disappointed": s.not_disappointed,
            "very_disappointed_share": s.very_disappointed_share,
        },
        "tools": [
            {
                "tool_id": t.tool_id,
                "calls": t.calls,
                "errors": t.errors,
                "success_rate": t.success_rate,
            }
            for t in tools
        ],
        "median_tool_success_rate": median_success,
        "gates": gates,
        "pmf_reached": all(gates.values()),
    }
