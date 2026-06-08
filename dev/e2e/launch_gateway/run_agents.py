"""Deploy 10 connectors and send an agent to USE each one.

For every connector in ``connectors.py`` this:
  1. builds + deploys it (discover -> create tools -> build -> export -> runtime),
  2. connects to the deployed runtime as an MCP agent and, for each task, reads
     ONLY the advertised tool descriptions + input schemas, selects a tool,
     fills its parameters from the schema, calls it, and judges the answer.

This measures Agent Experience: can a downstream agent actually accomplish real
tasks with what the connector exposes? Failures are diagnosed (tool-selection,
parameter, execution, or data) so they can be fixed. Run:
    uv run python dev/e2e/launch_gateway/run_agents.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dev.e2e.helpers.mcp_client import open_mcp_session  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402
from dev.e2e.launch_gateway.connectors import CONNECTORS, Connector, Task  # noqa: E402

_STOP = {
    "the",
    "a",
    "an",
    "of",
    "for",
    "in",
    "on",
    "to",
    "me",
    "my",
    "is",
    "are",
    "what",
    "which",
    "show",
    "give",
    "all",
    "number",
    "by",
    "with",
    "and",
    "that",
    "this",
    "how",
    "do",
    "i",
    "you",
    "it",
    "its",
    "their",
    "into",
    "please",
    "list",
    "return",
    "get",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in _STOP}


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


async def build_deploy(plugin_mcp: str, conn: Connector) -> tuple[bool, str, str]:
    """Returns (ok, exported_path, detail)."""
    async with open_mcp_session(plugin_mcp) as s:
        for src in conn.sources:
            ok, body = await _call(
                s,
                "elliot_discover_source",
                {"source_type": src.source_type, "config": src.discover_config(), "name": src.name},
            )
            if not ok:
                return False, "", f"discover {src.name} failed: {str(body)[:160]}"
        tool_ids = []
        for t in conn.tools:
            ok, body = await _call(
                s,
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
                return False, "", f"create_tool {t.name} failed: {str(body)[:160]}"
            tool_ids.append(body.get("tool_id", t.name))
        ok, body = await _call(
            s,
            "elliot_build_connector",
            {"name": conn.title, "slug": conn.id, "version": "1.0.0", "tool_ids": tool_ids},
        )
        if not ok:
            return False, "", f"build failed: {str(body)[:160]}"
        ok, body = await _call(
            s, "elliot_export_connector", {"path": f".elliot/connector_{conn.id}.json"}
        )
        if not ok:
            return False, "", f"export failed: {str(body)[:160]}"
        exported = body.get("path", "")
        ok, body = await _call(
            s, "elliot_start_runtime", {"port": 3001, "connector_path": exported}
        )
        if not ok:
            return False, "", f"start_runtime failed: {str(body)[:200]}"
        return True, exported, "deployed"


def _select_tool(task: Task, tools: list[Any]) -> Any:
    """Pick the tool whose name+description best matches the task, preferring
    one whose required params the task can satisfy (as an agent would)."""
    goal_tokens = _tokens(task.goal)
    scored = []
    for t in tools:
        desc = getattr(t, "description", "") or ""
        tool_tokens = _tokens(t.name + " " + desc)
        score = len(goal_tokens & tool_tokens)
        fillable = _missing_required(t, task) == []
        scored.append((score, fillable, t))
    if not scored:
        return None
    top = max(s[0] for s in scored)
    near = [x for x in scored if x[0] >= top - 1 and x[0] > 0]
    near.sort(key=lambda x: (x[1], x[0]), reverse=True)  # prefer fillable, then score
    return near[0][2] if near else max(scored, key=lambda x: x[0])[2]


def _schema(tool: Any) -> dict:
    return getattr(tool, "inputSchema", None) or {}


def _missing_required(tool: Any, task: Task) -> list[str]:
    schema = _schema(tool)
    required = schema.get("required", []) or []
    props = schema.get("properties", {}) or {}
    missing = []
    for name in required:
        if name in task.inputs:
            continue
        # Try matching by type when there's exactly one candidate input value.
        wanted = (props.get(name, {}) or {}).get("type")
        candidates = [v for v in task.inputs.values() if _json_type(v) == wanted]
        if len(candidates) == 1:
            continue
        missing.append(name)
    return missing


def _json_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    return "string"


def _fill_args(tool: Any, task: Task) -> dict:
    schema = _schema(tool)
    props = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    args: dict[str, Any] = {}
    for name, spec in props.items():
        if name in task.inputs:
            args[name] = task.inputs[name]
        elif name in required:
            wanted = (spec or {}).get("type")
            candidates = [v for v in task.inputs.values() if _json_type(v) == wanted]
            if len(candidates) == 1:
                args[name] = candidates[0]
    return args


def _rows(body: Any) -> list[dict]:
    if isinstance(body, dict):
        r = body.get("rows")
        if isinstance(r, list):
            return r
    return []


async def run_agent(runtime_mcp: str, conn: Connector) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    async with open_mcp_session(runtime_mcp) as s:
        listed = await s.list_tools()
        tools = list(listed.tools)
        for task in conn.tasks:
            tool = _select_tool(task, tools)
            if tool is None:
                out.append((task.goal, False, "agent: no tool matched the task"))
                continue
            missing = _missing_required(tool, task)
            if missing:
                out.append(
                    (
                        task.goal,
                        False,
                        f"agent picked '{tool.name}' but cannot fill required {missing}",
                    )
                )
                continue
            args = _fill_args(tool, task)
            ok, body = await _call(s, tool.name, args)
            if not ok:
                out.append(
                    (task.goal, False, f"call '{tool.name}'({args}) errored: {str(body)[:140]}")
                )
                continue
            rows = _rows(body)
            passed, detail = task.check(rows)
            out.append((task.goal, passed, f"used '{tool.name}'({args}) -> {detail}"))
    return out


async def stop_runtime(plugin_mcp: str) -> None:
    async with open_mcp_session(plugin_mcp) as s:
        await _call(s, "elliot_stop_runtime")


async def drive(plugin_mcp: str, runtime_url: str) -> dict:
    runtime_mcp = runtime_url.rstrip("/") + "/mcp/"
    summary: dict[str, Any] = {"connectors": [], "task_pass": 0, "task_fail": 0, "deploy_fail": 0}
    for conn in CONNECTORS:
        print(f"\n▶ {conn.id}: {conn.title}", flush=True)
        ok, exported, detail = await build_deploy(plugin_mcp, conn)
        if not ok:
            print(f"   ✗ deploy: {detail}", flush=True)
            summary["connectors"].append({"id": conn.id, "deployed": False, "detail": detail})
            summary["deploy_fail"] += 1
            continue
        print("   ✓ deployed", flush=True)
        time.sleep(0.8)
        results = await run_agent(runtime_mcp, conn)
        crec = {"id": conn.id, "deployed": True, "tasks": []}
        for goal, passed, d in results:
            mark = "✓" if passed else "✗"
            print(f"   {mark} agent task: {goal}  [{d}]", flush=True)
            crec["tasks"].append({"goal": goal, "ok": passed, "detail": d})
            summary["task_pass" if passed else "task_fail"] += 1
        summary["connectors"].append(crec)
        await stop_runtime(plugin_mcp)
        time.sleep(0.4)
    return summary


def main() -> int:
    print(f"Launch-gateway AGENT run: {len(CONNECTORS)} connectors")
    with elliot_stack(skip_studio=True, skip_runtime=True) as stack:
        summary = asyncio.run(drive(stack.plugin_mcp_url, stack.runtime_url))
    (HERE.parent / "agents_run.json").write_text(json.dumps(summary, indent=2))
    print("\n" + "=" * 70)
    print(
        f"connectors deployed: "
        f"{sum(1 for c in summary['connectors'] if c.get('deployed'))}/{len(CONNECTORS)}"
    )
    print(f"agent tasks: {summary['task_pass']} passed, {summary['task_fail']} failed")
    print("=" * 70)
    return 0 if summary["task_fail"] == 0 and summary["deploy_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
