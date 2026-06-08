"""Launch-gateway E2E harness: drive many real-world connector builds over MCP.

Boots the real Elliot plugin stack (same triple a user runs) and walks each
scenario in ``scenarios.py`` through the full build loop over the streamable-
HTTP MCP wire protocol — exactly what Studio / a coding agent sends:

    discover -> list -> sample -> create_tool* -> preview* -> build -> lint
    -> export   (+ start_runtime / health / stop for a representative subset)

Every step is recorded; a single failing step never aborts the run — the
point is to *collect* failures across all scenarios, then report.

Run:  uv run python dev/e2e/launch_gateway/run_scenarios.py
Env:  ELLIOT_GATEWAY_ONLY=s005_users,s009_pokemon_list  to filter scenarios.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))  # repo root, so `dev` is importable

from dev.e2e.helpers.mcp_client import open_mcp_session  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402
from dev.e2e.launch_gateway.scenarios import SCENARIOS, Scenario  # noqa: E402


@dataclass
class StepResult:
    step: str
    ok: bool
    detail: str = ""
    body: Any = None


@dataclass
class ScenarioResult:
    id: str
    title: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def add(self, step: str, ok: bool, detail: str = "", body: Any = None) -> StepResult:
        r = StepResult(step, ok, detail, body)
        self.steps.append(r)
        return r


async def _call(session: Any, name: str, args: dict | None = None) -> tuple[bool, Any]:
    """Call an MCP tool. Returns (ok, body). Never raises.

    ok is False when the transport errors, when the tool sets isError, or when
    the JSON body carries an ``error`` key (the plugin's soft-error shape).
    """
    try:
        result = await session.call_tool(name, args or {})
    except Exception as exc:  # transport / protocol failure
        return False, {"error": f"transport: {exc!r}"}

    body_text = None
    if result.content:
        body_text = getattr(result.content[0], "text", None)

    body: Any
    if result.structuredContent is not None:
        body = dict(result.structuredContent)
    elif body_text is not None:
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            body = {"text": body_text}
    else:
        body = {}

    if result.isError:
        return False, body if isinstance(body, dict) else {"error": str(body)}
    if isinstance(body, dict) and "error" in body:
        return False, body
    # `to_mcp_error_content` returns {"type":"text","text":"[CODE] message"} as a
    # non-isError result (see OBS-2). Detect that sentinel so we don't pass.
    if isinstance(body, dict):
        text = body.get("text")
        if isinstance(text, str) and re.match(r"^\[[A-Z][A-Z0-9_]*\]", text):
            return False, {"error": text}
    return True, body


async def run_scenario(mcp_url: str, runtime_url: str, sc: Scenario) -> ScenarioResult:
    res = ScenarioResult(sc.id, sc.title)
    async with open_mcp_session(mcp_url) as session:
        # 1. discover each source
        tables: dict[str, dict] = {}
        for src in sc.sources:
            ok, body = await _call(
                session,
                "elliot_discover_source",
                {"source_type": src.source_type, "config": src.config, "name": src.name},
            )
            if not ok:
                res.add(f"discover[{src.name}]", False, str(body.get("error", body))[:300], body)
                continue
            rc = body.get("row_count", 0)
            cols = set(body.get("columns", []))
            tables[src.name] = body
            detail = f"rows={rc} cols={len(cols)}"
            problems = []
            if rc < src.min_rows:
                problems.append(f"row_count {rc} < expected {src.min_rows}")
            missing = [c for c in src.expect_columns if c not in cols]
            if missing:
                problems.append(f"missing columns {missing} (have sample: {sorted(cols)[:12]})")
            if body.get("warnings"):
                detail += f" warnings={body['warnings']}"
            res.add(f"discover[{src.name}]", not problems, "; ".join(problems) or detail, body)

        # 2. list_sources sanity
        ok, body = await _call(session, "elliot_list_sources")
        res.add("list_sources", ok, "" if ok else str(body)[:200], None)

        # 3. sample each discovered table
        for name, info in tables.items():
            table_name = info.get("table_name")
            if not table_name:
                res.add(
                    f"sample[{name}]",
                    False,
                    f"discover body had no table_name: {str(info)[:200]}",
                    info,
                )
                continue
            ok, body = await _call(
                session, "elliot_sample_data", {"table_name": table_name, "limit": 3}
            )
            res.add(f"sample[{name}]", ok, "" if ok else str(body)[:200], None)

        # 4. create + preview each tool
        created_tool_ids: list[str] = []
        exported_path: str | None = None
        for t in sc.tools:
            ok, body = await _call(
                session,
                "elliot_create_tool",
                {
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "sql": t.sql,
                    "parameters": t.parameters,
                },
            )
            if not ok:
                res.add(f"create[{t.name}]", False, str(body.get("error", body))[:300], body)
                continue
            tool_id = body.get("tool_id", t.name)
            created_tool_ids.append(tool_id)
            res.add(f"create[{t.name}]", True, f"id={tool_id}")

            ok, body = await _call(
                session, "elliot_preview_tool", {"tool_id": tool_id, "params": t.preview_params}
            )
            if not ok:
                res.add(f"preview[{t.name}]", False, str(body.get("error", body))[:300], body)
                continue
            n = body.get("row_count", len(body.get("rows", [])) if isinstance(body, dict) else 0)
            empty_problem = t.expect_nonempty and n == 0
            res.add(
                f"preview[{t.name}]",
                not empty_problem,
                f"rows={n}" + (" (expected non-empty!)" if empty_problem else ""),
            )

        # 5. build connector for this scenario's tools
        if created_tool_ids:
            ok, body = await _call(
                session,
                "elliot_build_connector",
                {
                    "name": sc.title[:60],
                    "slug": sc.id.replace("_", "-"),
                    "version": "1.0.0",
                    "tool_ids": created_tool_ids,
                },
            )
            res.add(
                "build_connector",
                ok,
                str(body)[:200] if not ok else f"status={body.get('status')}",
                body,
            )

            # 6. lint
            ok, body = await _call(session, "elliot_lint_connector")
            if ok:
                ec = body.get("error_count", 0)
                wc = body.get("warning_count", 0)
                res.add("lint", ec == 0, f"errors={ec} warnings={wc}", body)
            else:
                res.add("lint", False, str(body)[:200], body)

            # 7. export
            dest = f".elliot/connector_{sc.id}.json"
            ok, body = await _call(session, "elliot_export_connector", {"path": dest})
            exported_path = body.get("path") if ok and isinstance(body, dict) else None
            res.add("export", ok, str(body.get("path", body))[:200], body)

        # 8. representative deploy — point the runtime at the connector we just
        # exported (an agent that exports to a custom path must pass it here).
        if sc.deploy and created_tool_ids and exported_path:
            ok, body = await _call(
                session,
                "elliot_start_runtime",
                {"port": 3001, "connector_path": exported_path},
            )
            res.add(
                "start_runtime",
                ok,
                str(body)[:200] if not ok else f"status={body.get('status')}",
                body,
            )
            if ok:
                health_ok = False
                detail = ""
                for _ in range(20):
                    try:
                        r = httpx.get(f"{runtime_url}/v1/health", timeout=3.0)
                        if r.status_code < 500:
                            health_ok = True
                            detail = f"http {r.status_code}: {r.text[:160]}"
                            break
                    except Exception as exc:
                        detail = repr(exc)
                    time.sleep(0.5)
                res.add("runtime_health", health_ok, detail)
                ok, body = await _call(session, "elliot_stop_runtime")
                res.add("stop_runtime", ok, f"status={body.get('status')}" if ok else str(body))
    return res


async def drive(mcp_url: str, runtime_url: str, scenarios: list[Scenario]) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for sc in scenarios:
        print(f"\n▶ {sc.id}: {sc.title}", flush=True)
        try:
            r = await run_scenario(mcp_url, runtime_url, sc)
        except Exception:
            r = ScenarioResult(sc.id, sc.title)
            r.add("FATAL", False, traceback.format_exc()[-800:])
        for st in r.steps:
            mark = "✓" if st.ok else "✗"
            print(f"   {mark} {st.step}: {st.detail}", flush=True)
        results.append(r)
    return results


def report(results: list[ScenarioResult]) -> dict:
    total_steps = sum(len(r.steps) for r in results)
    failed_steps = [(r.id, s) for r in results for s in r.steps if not s.ok]
    passed_scen = [r for r in results if r.ok]
    summary = {
        "scenarios": len(results),
        "scenarios_passed": len(passed_scen),
        "scenarios_failed": len(results) - len(passed_scen),
        "steps": total_steps,
        "steps_failed": len(failed_steps),
        "failures": [
            {"scenario": sid, "step": s.step, "detail": s.detail} for sid, s in failed_steps
        ],
    }
    return summary


def main() -> int:
    only = os.environ.get("ELLIOT_GATEWAY_ONLY", "").strip()
    scenarios = SCENARIOS
    if only:
        wanted = {x.strip() for x in only.split(",")}
        scenarios = [s for s in SCENARIOS if s.id in wanted]

    print(f"Launch-gateway harness: {len(scenarios)} scenarios", flush=True)
    with elliot_stack(skip_studio=True, skip_runtime=True) as stack:
        results = asyncio.run(drive(stack.plugin_mcp_url, stack.runtime_url, scenarios))

    summary = report(results)
    out = HERE.parent / "last_run.json"
    out.write_text(json.dumps(summary, indent=2))
    # Full per-step bodies for debugging.
    debug = [
        {
            "id": r.id,
            "steps": [
                {"step": s.step, "ok": s.ok, "detail": s.detail, "body": s.body} for s in r.steps
            ],
        }
        for r in results
    ]
    (HERE.parent / "last_run_debug.json").write_text(json.dumps(debug, indent=2, default=str))
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    print("=" * 70)
    print(f"\nReport written to {out}")
    return 0 if summary["steps_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
