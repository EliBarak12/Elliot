"""Layer 2 E2E: a real Claude Code agent builds the connector through Elliot's plugin.

This is the literal "real user installs Elliot, talks to it through Claude
Code" simulation. A fresh ``claude -p`` subprocess connects to the running
plugin via streamable HTTP, discovers Elliot's tools, and is asked — in
natural language — to build the same 4-source e-commerce-ops connector that
Layer 1 builds by hand. We assert from outside that the agent's session
state shows the right shape (sources, tools, lint clean, connector built).

The agent is constrained to ``mcp__elliot__*`` only — no Bash, Edit, or
direct file IO — so every change to session state must go through the
plugin under test.
"""

from __future__ import annotations

import os

import pytest

from .helpers.claude_agent import claude_is_available, run_claude_agent
from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

pytestmark = pytest.mark.skipif(
    not claude_is_available(),
    reason="claude CLI not on PATH — Layer 2 needs Claude Code installed",
)


@pytest.fixture(scope="module")
def stack(api_base_url: str):  # type: ignore[no-untyped-def]
    """Plugin only — agent talks to MCP, never opens Studio (saves 60s of Vite boot)."""
    with elliot_stack(skip_studio=True, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


AGENT_TASK = """\
You are testing the Elliot platform end-to-end. Build an e-commerce-ops MCP
connector that spans four REST APIs.

The four sources (all under the same base URL) are:
  • {base}/users      — customers with nested address.geo and company objects
  • {base}/products   — products with nested dimensions and meta
  • {base}/orders     — orders with a line_items[] array of {{product_id, quantity, unit_price}}
  • {base}/reviews    — product reviews with a nested reviewer object

Your job, using ONLY the Elliot MCP tools (mcp__elliot__*):

1. For each of the four URLs, call elliot_discover_source with source_type="rest"
   and a logical name (users, products, orders, reviews).
2. Use elliot_sample_data on at least one source to confirm nested columns
   flattened correctly (e.g. address_geo_lat exists on the users table).
3. Create at least three business tools via elliot_create_tool. The SQL runs
   against the flattened SQLite tables. Suggestions (you can adjust):
     - list_active_enterprise_customers (filter users by plan/status)
     - top_products_by_revenue (join orders_line_items × products, group/sum)
     - customer_order_history (filter orders by customer_id, order by date)
4. Call elliot_build_connector with slug="ecommerce-ops".
5. Call elliot_lint_connector and confirm zero ERROR-severity issues. If
   there are errors, fix the offending tool and re-lint.
6. Call elliot_export_connector with path="connectors/ecommerce-ops.connector.json"
   (relative paths land inside the workspace).
7. Call elliot_start_runtime to bring the connector live on port 3001.

When you're done, reply with a one-line JSON summary:
  {{"sources": N, "tools": M, "lint_errors": K, "runtime": "running"}}

Do not call any non-Elliot tools.
""".strip()


@pytest.mark.asyncio
async def test_agent_builds_connector_end_to_end(stack: StackEndpoints, api_base_url: str) -> None:
    prompt = AGENT_TASK.format(base=api_base_url)

    run = run_claude_agent(
        prompt,
        mcp_url=stack.plugin_mcp_url,
        workspace=stack.workspace,
        allowed_tools=["mcp__elliot__*"],
        max_budget_usd=float(os.environ.get("ELLIOT_E2E_AGENT_BUDGET_USD", "3.50")),
        timeout_seconds=900,
    )

    # Agent must have completed under budget without an error.
    assert run.succeeded, (
        f"Claude Code agent failed (exit={run.exit_code}, "
        f"turns={run.num_turns}, cost=${run.total_cost_usd:.2f}). "
        f"Last result text: {run.result_text!r}"
    )

    # Re-open an MCP session and verify the plugin's session state reflects
    # the agent's work. This is the equivalent of the user opening Studio
    # after the agent finishes and seeing the connector.
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        sources = await call_tool_json(session, "elliot_list_sources", {})
        names = {s["name"] for s in sources["sources"]}
        assert {"users", "products", "orders", "reviews"}.issubset(names), (
            f"Agent did not register all four sources; got {names}"
        )

        tools = await call_tool_json(session, "elliot_list_tools", {})
        assert tools["count"] >= 3, f"Agent created only {tools['count']} tools, expected ≥3"

        info = await call_tool_json(session, "studio_get_connector_info", {})
        assert info.get("connector_built") is True, f"Agent did not build a connector; info={info}"
        # `studio_get_connector_info` returns the full ConnectorConfig under
        # ``connector`` — its slug must match what the prompt asked for.
        connector = info.get("connector") or {}
        assert connector.get("slug") == "ecommerce-ops", (
            f"Agent built a connector with the wrong slug; got={connector.get('slug')!r}"
        )

        lint = await call_tool_json(session, "elliot_lint_connector", {})
        errors = [i for i in lint["issues"] if i["severity"] == "ERROR"]
        assert not errors, f"Agent left {len(errors)} lint ERRORs on the connector:\n" + "\n".join(
            f"  - {i['code']}: {i['message']}" for i in errors
        )

        # Clean up the runtime so the next test module can spawn its own.
        await call_tool_json(session, "elliot_stop_runtime", {})
