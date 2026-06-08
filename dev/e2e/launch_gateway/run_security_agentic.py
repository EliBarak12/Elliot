"""Launch-critical checks: secret hygiene + agentic build-loop features.

1. Secret hygiene — a connector built with bearer auth must keep the secret as
   a ``{{ env:VAR }}`` template in the exported file (safe to commit); the
   resolved secret value must never be written to disk. Also confirms an agent
   can actually fetch an auth-gated source via env-var resolution.
2. quality_scan — the connector quality scanner must flag a deliberately weak
   tool (vague description, no typed params) while passing a well-formed one.
3. run_eval — an eval suite runs against the live tools and reports pass/fail.

Run:  uv run python dev/e2e/launch_gateway/run_security_agentic.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dev.e2e.helpers.mcp_client import open_mcp_session  # noqa: E402
from dev.e2e.helpers.mock_apis import MockAPIServer  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402

SECRET_VALUE = "e2e-reviews-secret-001"  # the stack injects this as REVIEWS_TOKEN
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"   {'✓' if ok else '✗'} {name}: {detail}", flush=True)


async def _call(session: Any, name: str, args: dict | None = None) -> tuple[bool, Any]:
    try:
        result = await session.call_tool(name, args or {})
    except Exception as exc:
        return False, {"error": repr(exc)}
    text = getattr(result.content[0], "text", None) if result.content else None
    body: Any = {}
    if result.structuredContent is not None:
        body = dict(result.structuredContent)
    elif text is not None:
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"text": text}
    if result.isError or (isinstance(body, dict) and "error" in body):
        return False, body
    return True, body


async def drive(plugin_mcp: str, api_base: str, workspace: Path) -> None:
    async with open_mcp_session(plugin_mcp) as s:
        # ── 1. Secret hygiene ────────────────────────────────────────────────
        ok, body = await _call(
            s,
            "elliot_discover_source",
            {
                "source_type": "rest",
                "config": {
                    "url": f"{api_base}/reviews",
                    "auth": {"type": "bearer", "secret_key": "{{ env:REVIEWS_TOKEN }}"},
                },
                "name": "sec_reviews",
            },
        )
        record(
            "auth source discovered via env-var token",
            ok,
            f"rows={body.get('row_count')}" if ok else str(body)[:160],
        )

        await _call(
            s,
            "elliot_create_tool",
            {
                "name": "sec_list_reviews",
                "description": "List customer reviews with their rating and author.",
                "category": "READ",
                "sql": 'SELECT id, rating, reviewer_name FROM "sec_reviews"',
                "parameters": [],
            },
        )
        await _call(
            s,
            "elliot_build_connector",
            {"name": "Sec", "slug": "sec", "version": "1.0.0", "tool_ids": ["sec_list_reviews"]},
        )
        dest = str(workspace / "connectors" / "sec.json")
        ok, body = await _call(s, "elliot_export_connector", {"path": dest})
        record("connector exported", ok, str(body.get("path", body))[:120])

        # The exported file must contain the template, never the secret value.
        try:
            content = Path(dest).read_text()
            has_template = "{{ env:REVIEWS_TOKEN }}" in content or "REVIEWS_TOKEN" in content
            leaks_secret = SECRET_VALUE in content
            record("connector file keeps {{ env:VAR }} template", has_template, "")
            record(
                "connector file does NOT contain the resolved secret",
                not leaks_secret,
                "LEAK!" if leaks_secret else "no secret in file",
            )
        except Exception as exc:
            record("read exported connector", False, repr(exc))

        # ── 2. quality_scan flags a weak tool ────────────────────────────────
        # Create a deliberately weak tool (non-verb name, vague description,
        # SELECT *) and rebuild the connector so the scan covers it.
        await _call(
            s,
            "elliot_create_tool",
            {
                "name": "data",
                "description": "get data",
                "category": "READ",
                "sql": 'SELECT * FROM "sec_reviews"',
                "parameters": [],
            },
        )
        await _call(
            s,
            "elliot_build_connector",
            {
                "name": "Sec",
                "slug": "sec",
                "version": "1.0.0",
                "tool_ids": ["sec_list_reviews", "data"],
            },
        )
        ok, body = await _call(s, "elliot_quality_scan")
        if ok:
            scan = json.dumps(body)
            has_scores = "score" in scan
            # The weak tool should score lower than the well-formed one, and/or
            # the scan should surface issues for it.
            tool_scores = body.get("tool_scores", []) if isinstance(body, dict) else []
            by_id = {t.get("tool_id"): t for t in tool_scores}
            weak = by_id.get("data", {})
            good = by_id.get("sec_list_reviews", {})
            flagged = (
                body.get("warning_count", 0) > 0
                or (
                    weak.get("score") is not None
                    and good.get("score") is not None
                    and weak["score"] < good["score"]
                )
                or bool(weak.get("issues"))
            )
            record("quality_scan returns scores", has_scores, scan[:160])
            record(
                "quality_scan flags the weak tool",
                flagged,
                f"weak={weak.get('score')} good={good.get('score')} warns={body.get('warning_count')}",
            )
        else:
            record("quality_scan", False, str(body)[:160])

        # ── 3. run_eval executes a suite ─────────────────────────────────────
        eval_dir = workspace / ".elliot" / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "sec-smoke.json").write_text(
            json.dumps(
                {
                    "id": "sec-smoke",
                    "name": "Sec smoke",
                    "cases": [
                        {
                            "id": "reviews-non-empty",
                            "tool_id": "sec_list_reviews",
                            "params": {},
                            "match_mode": "shape",
                        }
                    ],
                }
            )
        )
        ok, body = await _call(s, "elliot_run_eval", {"suite_id": "sec-smoke"})
        record("run_eval executes the suite", ok, json.dumps(body)[:160] if ok else str(body)[:160])


def main() -> int:
    print("Launch-gateway SECURITY + AGENTIC checks")
    mock = MockAPIServer(port=8181)
    mock.start()
    try:
        with elliot_stack(skip_studio=True, skip_runtime=True) as stack:
            import os

            os.environ["ELLIOT_E2E_API_BASE"] = mock.base_url
            asyncio.run(drive(stack.plugin_mcp_url, mock.base_url, stack.workspace))
    finally:
        mock.stop()
    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 70)
    print(f"security+agentic: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for name, _ok, detail in failed:
        print(f"  FAIL {name}: {detail}")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
