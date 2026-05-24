"""Tests for the PMF (Sean Ellis + retention + success rate) roll-ups."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from elliot_connector_runtime.observation_store import ObservationStore
from elliot_connector_runtime.pmf import (
    kpi_brief,
    retention,
    sean_ellis,
    tool_success,
)


@pytest.fixture()
def store(tmp_path: Path) -> ObservationStore:
    return ObservationStore(f"sqlite:///{tmp_path}/obs.db")


def _backdate_session(store: ObservationStore, sid: str, days_ago: float) -> None:
    """Move an existing session's ``started_at`` back so it falls on a real day."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    target = time.time() - (days_ago * 86400)
    with Session(store._engine) as db:  # noqa: SLF001
        db.execute(
            text("UPDATE agent_sessions SET started_at = :ts WHERE session_id = :sid"),
            {"ts": target, "sid": sid},
        )
        db.commit()


def test_retention_counts_repeat_installations(store: ObservationStore) -> None:
    # Two sessions from the same client+version on two distinct days = repeat.
    store.open_session(
        "s1",
        agent_identity={"client": "claude-code", "client_version": "1.0.0"},
    )
    _backdate_session(store, "s1", days_ago=3)
    store.open_session(
        "s2",
        agent_identity={"client": "claude-code", "client_version": "1.0.0"},
    )
    _backdate_session(store, "s2", days_ago=1)
    # A different installation, only one day = not a repeat.
    store.open_session(
        "s3",
        agent_identity={"client": "cursor", "client_version": "0.42.0"},
    )
    _backdate_session(store, "s3", days_ago=2)

    r = retention(store, window_days=7)
    assert r.active_installations == 2
    assert r.repeat_installations == 1
    assert r.active_agents == 2


def test_retention_window_excludes_old_sessions(store: ObservationStore) -> None:
    store.open_session("old", agent_identity={"client": "claude-code"})
    _backdate_session(store, "old", days_ago=60)
    store.open_session("new", agent_identity={"client": "claude-code"})

    r = retention(store, window_days=14)
    assert r.active_installations == 1
    assert r.total_sessions == 1


def test_sean_ellis_threshold_passes_at_40pct(store: ObservationStore) -> None:
    # 4 very_disappointed out of 10 = exactly the 40% bar.
    for _ in range(4):
        store.write_feedback("__pmf_survey", "very_disappointed")
    for _ in range(3):
        store.write_feedback("__pmf_survey", "somewhat_disappointed")
    for _ in range(3):
        store.write_feedback("__pmf_survey", "not_disappointed")

    s = sean_ellis(store, window_days=30)
    assert s.responses == 10
    assert s.very_disappointed == 4
    assert s.very_disappointed_share == 0.4
    assert s.passes_threshold is True


def test_sean_ellis_ignores_non_pmf_feedback(store: ObservationStore) -> None:
    """A normal ``elliot_feedback`` call must not pollute the PMF count."""
    store.write_feedback("list_animals", "success")
    store.write_feedback("__pmf_survey", "very_disappointed")

    s = sean_ellis(store, window_days=30)
    assert s.responses == 1
    assert s.very_disappointed == 1


def test_tool_success_filters_low_volume_tools(store: ObservationStore) -> None:
    """A tool with only a handful of calls is noise, not signal — exclude it."""
    # 25 calls, 1 error -> success rate 24/25 = 0.96
    for _ in range(24):
        store.write_tool_call(None, "popular", {}, 1, 10, 1.0)
    store.write_tool_call(None, "popular", {}, 0, 0, 1.0, error="boom")
    # 5 calls — below threshold, must be excluded.
    for _ in range(5):
        store.write_tool_call(None, "rare", {}, 1, 10, 1.0)

    rows = tool_success(store, window_days=14, min_calls=20)
    assert {r.tool_id for r in rows} == {"popular"}
    [row] = rows
    assert row.success_rate == pytest.approx(0.96)


def test_kpi_brief_reports_all_three_gates(store: ObservationStore) -> None:
    """A fresh store fails every gate — that's the honest baseline."""
    brief = kpi_brief(store, window_days=14)
    assert brief["gates"]["active_installations_ge_10"] is False
    assert brief["gates"]["sean_ellis_ge_40pct"] is False
    assert brief["gates"]["median_success_ge_90pct"] is False
    assert brief["pmf_reached"] is False
    assert brief["retention"]["active_installations"] == 0
    assert brief["sean_ellis"]["responses"] == 0
