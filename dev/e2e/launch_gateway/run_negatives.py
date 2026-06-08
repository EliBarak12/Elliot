"""Negative / error-path checks for the launch gateway.

Principle #3 says errors must be actionable, and a launch must not crash or
silently mis-behave on bad input. This drives the real plugin over MCP and
asserts each failure mode is handled *gracefully* (structured error, server
stays alive) and that security invariants hold (read-only SQL, no statement
stacking). Each check prints PASS/FAIL with detail; a non-zero exit means at
least one invariant was violated.

Run:  uv run python dev/e2e/launch_gateway/run_negatives.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dev.e2e.helpers.mcp_client import open_mcp_session  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402

JP = "https://jsonplaceholder.typicode.com"
_ERR_SENTINEL = re.compile(r"^\[[A-Z][A-Z0-9_]*\]")


async def _call(session: Any, name: str, args: dict | None = None) -> tuple[bool, Any]:
    """Return (ok, body). ok=False on transport error, isError, {'error':...},
    or a [CODE] text sentinel."""
    try:
        result = await session.call_tool(name, args or {})
    except Exception as exc:
        return False, {"_transport_error": repr(exc)}
    text = getattr(result.content[0], "text", None) if result.content else None
    if result.structuredContent is not None:
        body: Any = dict(result.structuredContent)
    elif text is not None:
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"text": text}
    else:
        body = {}
    if result.isError:
        return False, body
    if isinstance(body, dict) and "error" in body:
        return False, body
    if (
        isinstance(body, dict)
        and isinstance(body.get("text"), str)
        and _ERR_SENTINEL.match(body["text"])
    ):
        return False, body
    return True, body


def _is_transport_crash(body: Any) -> bool:
    return isinstance(body, dict) and "_transport_error" in body


def _err_text(body: Any) -> str:
    if isinstance(body, dict):
        if "error" in body:
            return str(body["error"])
        if isinstance(body.get("text"), str):
            return body["text"]
    return str(body)


async def run_checks(mcp_url: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))
        print(f"   {'✓' if ok else '✗'} {name}: {detail}", flush=True)

    async with open_mcp_session(mcp_url) as session:
        # Seed one good table to test SQL paths against.
        ok, body = await _call(
            session,
            "elliot_discover_source",
            {"source_type": "rest", "config": {"url": f"{JP}/posts"}, "name": "neg_posts"},
        )
        record("seed discover posts", ok, "ready" if ok else _err_text(body))

        # N1 — discover a 404 URL: must fail gracefully, not crash.
        ok, body = await _call(
            session,
            "elliot_discover_source",
            {"source_type": "rest", "config": {"url": f"{JP}/no_such_path_xyz"}, "name": "neg_404"},
        )
        record(
            "N1 discover 404 → graceful error",
            (not ok) and not _is_transport_crash(body),
            _err_text(body)[:160],
        )

        # N2 — invalid source_type: actionable, lists valid types.
        ok, body = await _call(
            session,
            "elliot_discover_source",
            {"source_type": "ftp", "config": {"url": "ftp://x"}, "name": "neg_ftp"},
        )
        record(
            "N2 invalid source_type → actionable",
            (not ok) and not _is_transport_crash(body),
            _err_text(body)[:160],
        )

        # N3 — non-JSON (HTML) endpoint: must not crash the server.
        ok, body = await _call(
            session,
            "elliot_discover_source",
            {"source_type": "rest", "config": {"url": "https://example.com"}, "name": "neg_html"},
        )
        record(
            "N3 non-JSON endpoint → no crash",
            not _is_transport_crash(body),
            ("error: " + _err_text(body)[:120]) if not ok else "handled as result",
        )

        # N4 — invalid SQL at preview: actionable error, no crash.
        ok, _ = await _call(
            session,
            "elliot_create_tool",
            {
                "name": "neg_bad_sql",
                "description": "Intentionally broken SQL for negative test.",
                "category": "READ",
                "sql": "SELECT FROM WHERE",
                "parameters": [],
            },
        )
        if ok:
            ok2, body = await _call(session, "elliot_preview_tool", {"tool_id": "neg_bad_sql"})
            record(
                "N4 invalid SQL → actionable error",
                (not ok2) and not _is_transport_crash(body),
                _err_text(body)[:160],
            )
        else:
            # Rejected at create time — also acceptable (fail-fast).
            record("N4 invalid SQL → rejected at create", True, "create rejected it")

        # N5 — write statement must be blocked (read-only invariant).
        ok, body = await _call(
            session,
            "elliot_create_tool",
            {
                "name": "neg_delete",
                "description": "Attempt a destructive write — must be blocked.",
                "category": "READ",
                "sql": "DELETE FROM neg_posts",
                "parameters": [],
            },
        )
        blocked = not ok
        if ok:
            ok2, body = await _call(session, "elliot_preview_tool", {"tool_id": "neg_delete"})
            blocked = not ok2
        record("N5 write SQL (DELETE) → blocked (read-only)", blocked, _err_text(body)[:160])

        # N6 — statement stacking must be blocked.
        ok, body = await _call(
            session, "elliot_query_sql", {"sql": "SELECT 1; DROP TABLE neg_posts"}
        )
        record(
            "N6 statement stacking → blocked",
            (not ok) and not _is_transport_crash(body),
            _err_text(body)[:160],
        )

        # N7 — preview missing a required parameter: actionable.
        ok, _ = await _call(
            session,
            "elliot_create_tool",
            {
                "name": "neg_req_param",
                "description": "Tool requiring a parameter for negative test.",
                "category": "READ",
                "sql": 'SELECT * FROM "neg_posts" WHERE id = :id',
                "parameters": [
                    {"name": "id", "type": "integer", "required": True, "description": "post id"}
                ],
            },
        )
        if ok:
            ok2, body = await _call(session, "elliot_preview_tool", {"tool_id": "neg_req_param"})
            record(
                "N7 missing required param → actionable",
                (not ok2) and not _is_transport_crash(body),
                _err_text(body)[:160],
            )
        else:
            record("N7 create tool w/ required param", False, "unexpected create failure")

        # N8 — build_connector referencing a nonexistent tool: actionable.
        ok, body = await _call(
            session,
            "elliot_build_connector",
            {"name": "Neg", "slug": "neg", "version": "1.0.0", "tool_ids": ["does_not_exist"]},
        )
        record(
            "N8 build w/ unknown tool_id → actionable",
            (not ok) and not _is_transport_crash(body),
            _err_text(body)[:160],
        )

        # Server liveness: a normal call still works after all the abuse.
        ok, body = await _call(session, "elliot_list_sources")
        record(
            "N9 server still healthy after error storm",
            ok,
            "list_sources ok" if ok else _err_text(body),
        )

    return results


def main() -> int:
    print("Launch-gateway NEGATIVE checks")
    with elliot_stack(skip_studio=True, skip_runtime=True) as stack:
        results = asyncio.run(run_checks(stack.plugin_mcp_url))
    failed = [r for r in results if not r[1]]
    print("\n" + "=" * 70)
    print(f"negative checks: {len(results) - len(failed)}/{len(results)} passed")
    for name, _ok, detail in failed:
        print(f"  FAIL {name}: {detail}")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
