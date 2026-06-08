"""Multi-step agent chains — does the connector's tools actually COMPOSE?

Single-call tasks (run_agents.py) prove each tool works. Real agents chain
tools: call A, take a value out of A's result, feed it to B. That only works if
A's output actually exposes the field B needs — a concrete test of principle #2
(results shaped for the next step). For each chain this deploys the connector
and walks the steps, carrying the previous step's first-row fields forward, and
fails loudly if the data needed to continue isn't there.

Run:  uv run python dev/e2e/launch_gateway/run_chains.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dev.e2e.helpers.mcp_client import open_mcp_session  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402
from dev.e2e.launch_gateway.connectors import CONNECTORS, Task  # noqa: E402
from dev.e2e.launch_gateway.run_agents import (  # noqa: E402
    _call,
    _fill_args,
    _missing_required,
    _rows,
    _select_tool,
    build_deploy,
)


@dataclass
class Step:
    goal: str
    literal_inputs: dict = field(default_factory=dict)
    # param_name -> field in the PREVIOUS step's first row
    from_prev: dict = field(default_factory=dict)


@dataclass
class Chain:
    connector_id: str
    title: str
    steps: list[Step]
    # check(final_rows, context) -> (ok, detail)
    check: Callable[[list[dict], dict], tuple[bool, str]]


def build_chains() -> list[Chain]:
    chains: list[Chain] = []

    # Blog: find a user by name, then list THAT user's posts (id must flow A->B).
    chains.append(
        Chain(
            connector_id="c01",
            title="Find user by name, then list their posts",
            steps=[
                Step(
                    "Find the user whose full name is Leanne Graham.",
                    literal_inputs={"name": "Leanne Graham"},
                ),
                Step("List all blog posts written by that user.", from_prev={"user_id": "id"}),
            ],
            check=lambda rows, ctx: (
                len(rows) > 0
                and all(str(r.get("userid")) == str(ctx.get("user_id")) for r in rows),
                f"rows={len(rows)} user_id={ctx.get('user_id')}",
            ),
        )
    )

    # Catalog: discover categories, then list products in the first category.
    chains.append(
        Chain(
            connector_id="c02",
            title="Discover categories, then list products in the first one",
            steps=[
                Step("What product categories are available?"),
                Step("List the products in that category.", from_prev={"category": "category"}),
            ],
            check=lambda rows, ctx: (
                len(rows) > 0 and all(r.get("category") == ctx.get("category") for r in rows),
                f"rows={len(rows)} category={ctx.get('category')}",
            ),
        )
    )

    # Photos: find the busiest album, then list the photos in it.
    chains.append(
        Chain(
            connector_id="c10",
            title="Find the busiest album, then list its photos",
            steps=[
                # No inputs here on purpose: the only tool the agent can fill is
                # photo_count_per_album (no required params); photos_in_album
                # needs album_id it doesn't have yet. That id must come from the
                # first step's result for the chain to work.
                Step("Which album has the most photos?"),
                Step("List the photos that are in that album.", from_prev={"album_id": "albumid"}),
            ],
            check=lambda rows, ctx: (
                len(rows) > 0
                and all(str(r.get("albumid")) == str(ctx.get("album_id")) for r in rows),
                f"rows={len(rows)} album_id={ctx.get('album_id')}",
            ),
        )
    )

    return chains


CHAINS = build_chains()
_CONN_BY_ID = {c.id: c for c in CONNECTORS}


async def run_chain(runtime_mcp: str, chain: Chain) -> tuple[bool, str]:
    async with open_mcp_session(runtime_mcp) as s:
        listed = await s.list_tools()
        tools = list(listed.tools)
        prev_rows: list[dict] = []
        context: dict[str, Any] = {}
        for i, step in enumerate(chain.steps):
            inputs = dict(step.literal_inputs)
            # Resolve values that must flow from the previous step's result.
            for param, src_field in step.from_prev.items():
                if not prev_rows:
                    return False, f"step {i}: no rows from previous step to read '{src_field}'"
                if src_field not in prev_rows[0]:
                    return (
                        False,
                        f"step {i}: previous result has no field '{src_field}' "
                        f"(available: {sorted(prev_rows[0].keys())}) — tools don't compose",
                    )
                inputs[param] = prev_rows[0][src_field]
                context[param] = prev_rows[0][src_field]
            # The agent picks a tool for this sub-goal from descriptions+schema.
            task = Task(goal=step.goal, inputs=inputs)
            tool = _select_tool(task, tools)
            if tool is None:
                return False, f"step {i}: no tool matched '{step.goal}'"
            missing = _missing_required(tool, task)
            if missing:
                return False, f"step {i}: picked '{tool.name}' but cannot fill {missing}"
            args = _fill_args(tool, task)
            ok, body = await _call(s, tool.name, args)
            if not ok:
                return False, f"step {i}: '{tool.name}'({args}) errored: {str(body)[:140]}"
            prev_rows = _rows(body)
            print(f"      step {i}: '{tool.name}'({args}) -> rows={len(prev_rows)}", flush=True)
        ok, detail = chain.check(prev_rows, context)
        return ok, detail


async def stop_runtime(plugin_mcp: str) -> None:
    async with open_mcp_session(plugin_mcp) as s:
        await _call(s, "elliot_stop_runtime")


async def drive(plugin_mcp: str, runtime_url: str) -> tuple[int, int]:
    runtime_mcp = runtime_url.rstrip("/") + "/mcp/"
    passed = failed = 0
    for chain in CHAINS:
        conn = _CONN_BY_ID[chain.connector_id]
        print(f"\n▶ {chain.connector_id} chain: {chain.title}", flush=True)
        ok, exported, detail = await build_deploy(plugin_mcp, conn)
        if not ok:
            print(f"   ✗ deploy: {detail}", flush=True)
            failed += 1
            continue
        time.sleep(0.8)
        ok, detail = await run_chain(runtime_mcp, chain)
        print(f"   {'✓' if ok else '✗'} chain result: {detail}", flush=True)
        passed += int(ok)
        failed += int(not ok)
        await stop_runtime(plugin_mcp)
        time.sleep(0.4)
    return passed, failed


def main() -> int:
    print(f"Launch-gateway CHAIN run: {len(CHAINS)} multi-step chains")
    with elliot_stack(skip_studio=True, skip_runtime=True) as stack:
        passed, failed = asyncio.run(drive(stack.plugin_mcp_url, stack.runtime_url))
    print("\n" + "=" * 70)
    print(f"chains: {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
