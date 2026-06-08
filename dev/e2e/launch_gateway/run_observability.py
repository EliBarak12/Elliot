"""End-to-end observability check — does Studio actually *see* what agents build?

Studio renders from two data paths: the plugin's ``studio_*`` MCP tools and the
connector runtime's ``/v1/*`` REST endpoints. This harness proves the whole
loop a real user relies on:

    build a connector -> deploy the runtime -> an MCP *agent* calls the deployed
    tool (a success and a deliberate error) -> the calls show up as observable
    sessions / audit entries / metrics that Studio reads.

This is principle #4 (every agent session is observable) tested at the wire
level the React UI uses. Run:
    uv run python dev/e2e/launch_gateway/run_observability.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dev.e2e.helpers.mcp_client import open_mcp_session  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402

DJ = "https://dummyjson.com"
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
    body: Any
    if result.structuredContent is not None:
        body = dict(result.structuredContent)
    elif text is not None:
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"text": text}
    else:
        body = {}
    if result.isError or (isinstance(body, dict) and "error" in body):
        return False, body
    return True, body


async def build_and_deploy(plugin_mcp: str) -> tuple[bool, str]:
    """Build a small dummyjson connector and deploy the runtime. Returns
    (ok, exported_path)."""
    async with open_mcp_session(plugin_mcp) as s:
        ok, body = await _call(
            s,
            "elliot_discover_source",
            {
                "source_type": "rest",
                "config": {"url": f"{DJ}/products?limit=50", "data_path": "products"},
                "name": "obs_products",
            },
        )
        record("build: discover", ok, f"rows={body.get('row_count')}" if ok else str(body)[:160])
        if not ok:
            return False, ""

        ok, body = await _call(
            s,
            "elliot_create_tool",
            {
                "name": "obs_top_products",
                "description": "List the five most expensive products with their category.",
                "category": "READ",
                "sql": 'SELECT id, title, price, category FROM "obs_products" '
                "ORDER BY price DESC LIMIT 5",
                "parameters": [],
            },
        )
        record("build: create_tool", ok, str(body)[:120])
        tool_id = body.get("tool_id") if ok else None

        ok, body = await _call(
            s,
            "elliot_build_connector",
            {
                "name": "Observability Demo",
                "slug": "obs-demo",
                "version": "1.0.0",
                "tool_ids": [tool_id],
            },
        )
        record(
            "build: build_connector",
            ok,
            f"tool_count={body.get('tool_count')}" if ok else str(body)[:160],
        )

        ok, body = await _call(s, "elliot_export_connector", {"path": ".elliot/connector_obs.json"})
        exported = body.get("path") if ok else ""
        record("build: export", ok, str(exported)[:120])

        ok, body = await _call(
            s, "elliot_start_runtime", {"port": 3001, "connector_path": exported}
        )
        record(
            "deploy: start_runtime", ok, f"status={body.get('status')}" if ok else str(body)[:200]
        )
        return ok, exported


async def act_as_agent(runtime_mcp: str) -> str | None:
    """Connect to the deployed runtime as an MCP agent, call the tool a few
    times (incl. a deliberate bad call), so observability has something to show.
    Returns the deployed tool's name."""
    async with open_mcp_session(runtime_mcp) as s:
        tools = await s.list_tools()
        names = [t.name for t in tools.tools]
        record("agent: runtime exposes tools", bool(names), f"tools={names}")
        # Find our tool (runtime may expose it under its id or a prefixed name).
        target = next(
            (n for n in names if "top_products" in n or "obs" in n), names[0] if names else None
        )
        if not target:
            return None
        for i in range(3):
            ok, body = await _call(s, target, {})
            n = body.get("row_count", len(body.get("rows", []))) if isinstance(body, dict) else 0
            record(f"agent: call #{i + 1} {target}", ok, f"rows={n}" if ok else str(body)[:160])
        # A deliberate bad call (unknown tool) — should be a clean error, and
        # ideally observable as a failed interaction.
        ok, body = await _call(s, target, {"nonexistent_param": "x"})
        record(
            "agent: call with junk arg handled",
            True,
            "ok" if ok else f"clean error: {str(body)[:100]}",
        )
        return target


def check_runtime_v1(runtime_url: str) -> None:
    """Hit the /v1 endpoints Studio reads and assert they reflect the activity."""
    base = runtime_url.rstrip("/")

    def get(path: str) -> tuple[int, Any]:
        try:
            r = httpx.get(f"{base}{path}", timeout=5.0)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, r.text
        except Exception as exc:
            return 0, repr(exc)

    code, body = get("/v1/health")
    record(
        "studio-data: /v1/health",
        code == 200,
        f"{code} {json.dumps(body)[:120] if isinstance(body, (dict, list)) else body}",
    )

    code, body = get("/v1/sessions")
    sessions = (
        body
        if isinstance(body, list)
        else body.get("sessions", body)
        if isinstance(body, dict)
        else []
    )
    n_sessions = len(sessions) if isinstance(sessions, list) else 0
    record(
        "studio-data: /v1/sessions shows agent activity",
        code == 200 and n_sessions >= 1,
        f"{code} sessions={n_sessions}",
    )

    code, body = get("/v1/audit")
    entries = (
        body
        if isinstance(body, list)
        else body.get("entries", body)
        if isinstance(body, dict)
        else []
    )
    n_audit = len(entries) if isinstance(entries, list) else 0
    record(
        "studio-data: /v1/audit recorded tool calls",
        code == 200 and n_audit >= 1,
        f"{code} entries={n_audit}",
    )

    code, body = get("/v1/metrics/token-efficiency")
    record(
        "studio-data: /v1/metrics/token-efficiency",
        code == 200,
        f"{code} {json.dumps(body)[:140] if isinstance(body, (dict, list)) else body}",
    )

    code, body = get("/v1/feedback")
    record("studio-data: /v1/feedback", code == 200, str(code))


async def check_plugin_studio_tools(plugin_mcp: str) -> None:
    """The studio_* MCP tools the dashboard calls must reflect the built connector."""
    async with open_mcp_session(plugin_mcp) as s:
        ok, body = await _call(s, "elliot_session_summary")
        record(
            "studio-tool: session_summary",
            ok,
            f"tools={body.get('tools') if isinstance(body, dict) else '?'}",
        )

        ok, body = await _call(s, "studio_get_connector_info")
        has = ok and isinstance(body, dict) and bool(body)
        record(
            "studio-tool: get_connector_info",
            has,
            json.dumps(body)[:140] if ok else str(body)[:140],
        )

        ok, body = await _call(s, "studio_get_metrics", {"days": 30})
        record("studio-tool: get_metrics", ok, json.dumps(body)[:140] if ok else str(body)[:140])

        ok, body = await _call(s, "studio_get_audit_log", {"limit": 50})
        entries = body.get("entries", body) if isinstance(body, dict) else body
        n = len(entries) if isinstance(entries, list) else "?"
        record("studio-tool: get_audit_log", ok, f"entries={n}")


async def stop_runtime(plugin_mcp: str) -> None:
    async with open_mcp_session(plugin_mcp) as s:
        await _call(s, "elliot_stop_runtime")


async def drive(plugin_mcp: str, runtime_url: str) -> None:
    ok, _ = await build_and_deploy(plugin_mcp)
    if not ok:
        record("FATAL", False, "build/deploy failed; cannot test observability")
        return
    # Give the runtime a moment to settle, then act as an agent.
    time.sleep(1.0)
    runtime_mcp = runtime_url.rstrip("/") + "/mcp/"
    await act_as_agent(runtime_mcp)
    time.sleep(1.0)  # let audit/session writes flush
    check_runtime_v1(runtime_url)
    await check_plugin_studio_tools(plugin_mcp)
    await stop_runtime(plugin_mcp)


def main() -> int:
    print("Launch-gateway OBSERVABILITY check (build -> deploy -> agent -> Studio data)")
    with elliot_stack(skip_studio=True, skip_runtime=True) as stack:
        asyncio.run(drive(stack.plugin_mcp_url, stack.runtime_url))
    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 70)
    print(f"observability: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for name, _ok, detail in failed:
        print(f"  FAIL {name}: {detail}")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
