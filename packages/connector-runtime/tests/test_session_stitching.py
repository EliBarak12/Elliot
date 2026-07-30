"""Tests for stitch_stateless_fragments — logical sessions on a stateless wire.

Ported from Elliot Cloud's observability tests (which carried its own copy of
this logic) and extended with the exact-handle grouping the 2026-07-28
upgrade adds: fragments sharing a server-minted ``es_…`` handle merge
regardless of the idle gap.
"""

from __future__ import annotations

from typing import Any

from elliot_connector_runtime.session_tracker import stitch_stateless_fragments


def _fragment(
    sid: str,
    ts: float,
    *,
    client: str | None = "claude",
    model: str | None = "opus",
    tool_id: str = "list_things",
    source: str = "mcp",
) -> dict[str, Any]:
    identity = {"client": client, "model": model} if client else None
    return {
        "session_id": sid,
        "started_at": ts,
        "last_activity": ts,
        "agent_hint": client or "mcp",
        "agent_identity": identity,
        "source": source,
        "events": [
            {
                "ts": ts,
                "type": "tool_call",
                "tool_id": tool_id,
                "duration_ms": 10.0,
                "result_rows": 1,
                "result_token_estimate": 5,
            }
        ],
    }


class TestHeuristicStitching:
    def test_stateless_fragments_stitch_into_one_journey(self) -> None:
        raw = [_fragment(f"req-{i:08d}", 1000.0 + i * 10) for i in range(4)]
        out = stitch_stateless_fragments(raw)
        assert len(out) == 1
        assert out[0]["total_tool_calls"] == 4
        # The earliest fragment's id is the stable logical id.
        assert out[0]["session_id"] == "req-00000000"

    def test_idle_gap_splits_sessions(self) -> None:
        raw = [
            _fragment("req-aaaaaaaa", 1000.0),
            _fragment("req-bbbbbbbb", 1000.0 + 2000.0),  # > 15 min later
        ]
        out = stitch_stateless_fragments(raw)
        assert len(out) == 2

    def test_different_agents_do_not_merge(self) -> None:
        raw = [
            _fragment("req-aaaaaaaa", 1000.0, client="claude"),
            _fragment("req-bbbbbbbb", 1010.0, client="cursor"),
        ]
        out = stitch_stateless_fragments(raw)
        assert len(out) == 2

    def test_hook_sessions_pass_through_untouched(self) -> None:
        hook = _fragment("hook-session-1", 500.0, source="hook")
        hook["user_prompt"] = "do the thing"
        out = stitch_stateless_fragments([hook, _fragment("req-aaaaaaaa", 1000.0)])
        hooks = [s for s in out if s.get("source") == "hook"]
        assert hooks == [hook]


class TestExactHandleGrouping:
    def test_shared_minted_handle_merges_regardless_of_gap(self) -> None:
        # Same es_ handle across a > idle-gap pause: still ONE journey —
        # the client explicitly told us so by echoing the handle.
        raw = [
            _fragment("es_abc123abc123", 1000.0),
            _fragment("es_abc123abc123", 1000.0 + 5000.0),
        ]
        out = stitch_stateless_fragments(raw)
        assert len(out) == 1
        assert out[0]["session_id"] == "es_abc123abc123"
        assert out[0]["total_tool_calls"] == 2

    def test_repeated_client_correlation_id_groups_exactly(self) -> None:
        # A non-Elliot id that recurs was a deliberate client correlation id.
        raw = [
            _fragment("harness-run-42", 1000.0),
            _fragment("harness-run-42", 1000.0 + 3000.0),
            _fragment("req-aaaaaaaa", 1005.0, client="cursor"),
        ]
        out = stitch_stateless_fragments(raw)
        by_id = {s["session_id"]: s for s in out}
        assert by_id["harness-run-42"]["total_tool_calls"] == 2
        assert len(out) == 2

    def test_handle_groups_do_not_absorb_other_agents(self) -> None:
        raw = [
            _fragment("es_abc123abc123", 1000.0, client="claude"),
            _fragment("req-aaaaaaaa", 1001.0, client="claude"),
        ]
        out = stitch_stateless_fragments(raw)
        # The handle-bearing fragment stays its own exact session; the loose
        # one is a separate heuristic session.
        assert len(out) == 2

    def test_signals_and_summary_come_from_runtime_code(self) -> None:
        raw = [_fragment("es_abc123abc123", 1000.0)]
        out = stitch_stateless_fragments(raw)
        assert "signals" in out[0] and "summary" in out[0]
