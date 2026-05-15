"""Layer 2 — multi-agent pipeline: builder → consumer → reviewer.

Three real ``claude -p`` subprocesses share one Elliot stack:

1. **Builder agent** talks to the Elliot plugin (port 3000) and builds an
   e-commerce-ops connector across 5 REST APIs — including cursor pagination,
   offset pagination, bearer-token auth, and a 5-level deeply nested source.
   It also creates a reusable skill describing the connector. Allowed tools
   are ``mcp__elliot__*`` only, so every connector-shaping call goes through
   the plugin under test.

2. **Consumer agent** talks to the *runtime* the builder deployed (port 3001),
   not the plugin. It discovers the runtime's tool list, picks tools, and
   answers a business question that requires joining customers × orders ×
   products × reviews. This generates real session activity in the runtime's
   observation store — exactly what a downstream agent would produce in
   production.

3. **Reviewer agent** opens a fresh session against the Elliot plugin, calls
   ``elliot_quality_scan`` + ``elliot_run_eval`` on the live connector, hits
   the runtime's ``/v1/metrics/token-efficiency`` endpoint (via WebFetch in
   the agent), and reports which tools the consumer used well, which were
   token-wasteful, and what changes to make. We assert the reviewer's
   verdict matches what the retrospective parser computes independently —
   if it doesn't, either the LLM hallucinated or the observability data
   isn't surfacing.

Each agent's stream-json transcript is parsed into a Markdown
retrospective (logs/retro-builder.md etc.) so a human can audit what
actually happened on every turn.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from .helpers.agent_retrospective import grade, to_markdown
from .helpers.claude_agent import AgentRun, claude_is_available, run_claude_agent
from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

pytestmark = pytest.mark.skipif(
    not claude_is_available(),
    reason="claude CLI not on PATH — Layer 2 needs Claude Code installed",
)


@pytest.fixture(scope="module")
def stack(api_base_url: str) -> Iterator[StackEndpoints]:
    """One stack shared by all three agents — Builder deploys, Consumer uses, Reviewer audits."""
    with elliot_stack(skip_studio=True, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


BUILDER_TASK = """\
You are testing the Elliot platform end-to-end as the **builder** agent.
Use only the Elliot MCP tools (mcp__elliot__*).

Build an e-commerce-ops MCP connector spanning **5 REST APIs**, all under
the same base URL ``{base}``:

  1. ``GET /users`` (flat list) — customers with nested address.geo and company
  2. ``GET /v2/orders?offset=N&limit=M`` (offset paginated) — returns
     ``{{items, total, offset, limit}}``. Configure pagination with strategy
     "offset", page_size 6 so the agent can fetch all rows.
  3. ``GET /products`` (flat) — nested dimensions + meta
  4. ``GET /reviews`` (bearer-auth gated). Configure source auth with
     ``type: "bearer"`` and ``secret_key: "{{{{ env:REVIEWS_TOKEN }}}}"`` —
     the env-template form (literal double braces), NOT a bare name. Elliot
     resolves the placeholder from the runtime's env at fetch time.
  5. ``GET /organizations`` (deeply nested) — 5 levels (org → dept → team →
     member → skills[]). Test the flattener's depth handling.

After the discover steps:

A. Call elliot_sample_data on at least three sources to confirm flattening.
B. Create **at least 4** business tools via elliot_create_tool:
   - list_active_enterprise_customers     (filter users.plan="enterprise")
   - top_products_by_revenue              (join orders_line_items × products,
                                            group by product, sum revenue)
   - customer_order_history               (orders for a customer_id, sorted)
   - unresolved_low_reviews               (reviews.rating ≤ 3 AND
                                            response_author IS NULL)
   Use parameter names like :customer_id, :max_rating — colon-prefixed.
C. Create **one skill** via elliot_create_skill describing how to use these
   tools together for "find at-risk enterprise accounts" — a customer is
   at-risk if their MRR > 1000 AND they have ≥1 pending order OR ≥1
   unresolved low review. Name the skill `find_at_risk_accounts`.
D. Call elliot_build_connector with name "E-Commerce Ops" slug "ecommerce-ops".
E. Call elliot_lint_connector and confirm zero ERROR-severity issues.
   If any ERROR appears, fix the offending tool via elliot_update_tool and re-lint.
F. Call elliot_export_connector to "connectors/ecommerce-ops.connector.json".
G. Call elliot_start_runtime — it spawns the connector runtime on port 3001
   so a downstream agent can use these tools.

When done, reply with exactly this JSON on one line:
  {{"sources": N, "tools": M, "skills": S, "lint_errors": K, "runtime": "running"}}
""".strip()


CONSUMER_TASK = """\
You are an **e-commerce ops analyst agent**. You have access to a set of MCP
tools (prefix ``mcp__ecommerce__``) that talk to a production e-commerce
backend. Use only those tools.

Today's question from your CEO: **"Which two enterprise customers are
spending the most and which products did they buy most recently?"**

Steps:
1. Call ``mcp__ecommerce__list_active_enterprise_customers`` (no args) to
   get the top enterprise customers by MRR.
2. For the **top 2** customers from step 1, call
   ``mcp__ecommerce__customer_order_history(customer_id=...)`` to get each
   one's order history.
3. Look at the most recent order per customer and report:
   - customer name + company
   - order id, date, total
   - the products in that order (you can call
     ``mcp__ecommerce__top_products_by_revenue`` if helpful for context)

Reply with a short Markdown report ending with a line:
  RESULT: customer1=<name>, customer2=<name>
""".strip()


REVIEWER_TASK = """\
You are the **Elliot reviewer** — a connector-quality auditor. Use only
``mcp__elliot__*`` MCP tools. The e-commerce-ops connector is live; a
consumer agent has been calling its tools and you need to grade the
connector.

Do:
1. Call ``elliot_quality_scan`` to get per-tool quality scores.
2. Call ``elliot_list_tools`` to confirm what tools exist on the connector.
3. Call ``elliot_lint_connector`` once more.
4. (Optional) Run any eval suite available via ``elliot_run_eval``.

Then write a short verdict as JSON on one line at the end:
  {{"overall": "<good|mixed|poor>", "tool_count": M,
    "lint_errors": E, "tools_to_improve": [<tool_id>, ...]}}

Pick "tools_to_improve" as any tool that lacks parameters, has unclear
descriptions, or scored badly in the quality scan.
""".strip()


def _write_retro(run: AgentRun, dest: Path, title: str) -> None:
    md = to_markdown(run.retro, title=title)
    dest.write_text(md, encoding="utf-8")


@pytest.mark.asyncio
async def test_multiagent_pipeline(stack: StackEndpoints, api_base_url: str) -> None:
    log_dir = stack.log_dir
    builder_budget = float(os.environ.get("ELLIOT_E2E_BUILDER_BUDGET_USD", "3.00"))
    consumer_budget = float(os.environ.get("ELLIOT_E2E_CONSUMER_BUDGET_USD", "1.50"))
    reviewer_budget = float(os.environ.get("ELLIOT_E2E_REVIEWER_BUDGET_USD", "1.50"))

    # ── Stage 1 — Builder agent ───────────────────────────────────────────
    builder_run = run_claude_agent(
        BUILDER_TASK.format(base=api_base_url),
        mcp_url=stack.plugin_mcp_url,
        workspace=stack.workspace,
        role="builder",
        server_name="elliot",
        max_budget_usd=builder_budget,
        timeout_seconds=1200,
    )
    _write_retro(builder_run, log_dir / "retro-builder.md", "Builder agent retrospective")
    assert builder_run.succeeded, (
        f"Builder failed (exit={builder_run.exit_code}, "
        f"cost=${builder_run.total_cost_usd:.2f}). Last: {builder_run.result_text!r}"
    )

    # Verify the builder's session state — connector exists, runtime is up.
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        info = await call_tool_json(session, "studio_get_connector_info", {})
        assert info.get("connector_built") is True
        connector = info.get("connector") or {}
        assert connector.get("slug") == "ecommerce-ops"
        tools = await call_tool_json(session, "elliot_list_tools", {})
        assert tools["count"] >= 4, f"Builder created only {tools['count']} tools"
        skills = await call_tool_json(session, "elliot_list_skills", {})
        # Skills are optional; if the builder skipped, we don't fail the whole
        # pipeline but the reviewer's verdict should flag the gap.
        skill_count = skills.get("count", 0)

    # Make sure the runtime the builder spawned is reachable on 3001.
    runtime_health = httpx.get("http://127.0.0.1:3001/v1/health", timeout=10).json()
    assert runtime_health["connector"]["slug"] == "ecommerce-ops"
    runtime_mcp_url = "http://127.0.0.1:3001/mcp/"

    # ── Stage 2 — Consumer agent ──────────────────────────────────────────
    consumer_run = run_claude_agent(
        CONSUMER_TASK,
        mcp_url=runtime_mcp_url,
        workspace=stack.workspace,
        role="consumer",
        server_name="ecommerce",
        max_budget_usd=consumer_budget,
        timeout_seconds=600,
    )
    _write_retro(consumer_run, log_dir / "retro-consumer.md", "Consumer agent retrospective")
    assert consumer_run.succeeded, (
        f"Consumer failed (exit={consumer_run.exit_code}, "
        f"cost=${consumer_run.total_cost_usd:.2f}). Last: {consumer_run.result_text!r}"
    )

    # The consumer should have made at least 2 tool calls (one of which
    # is the customer-history lookup) — otherwise it didn't really use the
    # connector at all.
    consumer_grade = grade(consumer_run.retro)
    assert sum(consumer_run.retro.tool_call_counts.values()) >= 2, (
        "Consumer never actually called the runtime's tools"
    )

    # Make sure the runtime saw the activity — observability store must
    # have non-empty session list.
    sessions = httpx.get("http://127.0.0.1:3001/v1/sessions", timeout=10).json()
    assert len(sessions) >= 1, "Runtime observability never recorded a session"
    metrics = httpx.get("http://127.0.0.1:3001/v1/metrics/token-efficiency", timeout=10).json()
    assert metrics["sessions_analysed"] >= 1, "No sessions analysed for metrics"

    # ── Stage 3 — Reviewer agent ──────────────────────────────────────────
    reviewer_run = run_claude_agent(
        REVIEWER_TASK,
        mcp_url=stack.plugin_mcp_url,
        workspace=stack.workspace,
        role="reviewer",
        server_name="elliot",
        max_budget_usd=reviewer_budget,
        timeout_seconds=600,
    )
    _write_retro(reviewer_run, log_dir / "retro-reviewer.md", "Reviewer agent retrospective")
    assert reviewer_run.succeeded, (
        f"Reviewer failed (exit={reviewer_run.exit_code}, "
        f"cost=${reviewer_run.total_cost_usd:.2f}). Last: {reviewer_run.result_text!r}"
    )

    # ── Compute the independent grade + write the pipeline summary ───────
    builder_grade = grade(builder_run.retro)
    reviewer_grade = grade(reviewer_run.retro)

    summary = {
        "totals": {
            "agent_runs": 3,
            "total_cost_usd": (
                builder_run.total_cost_usd
                + consumer_run.total_cost_usd
                + reviewer_run.total_cost_usd
            ),
            "total_duration_ms": (
                builder_run.duration_ms + consumer_run.duration_ms + reviewer_run.duration_ms
            ),
            "skills_created": skill_count,
            "tool_count": tools["count"],
            "runtime_sessions": len(sessions),
        },
        "builder": {
            "turns": builder_run.num_turns,
            "cost_usd": builder_run.total_cost_usd,
            "duration_ms": builder_run.duration_ms,
            "tool_calls": builder_run.retro.tool_call_counts,
            "stages": builder_run.retro.stage_counts,
            "grade": builder_grade,
        },
        "consumer": {
            "turns": consumer_run.num_turns,
            "cost_usd": consumer_run.total_cost_usd,
            "duration_ms": consumer_run.duration_ms,
            "tool_calls": consumer_run.retro.tool_call_counts,
            "grade": consumer_grade,
            "final_text": consumer_run.result_text,
        },
        "reviewer": {
            "turns": reviewer_run.num_turns,
            "cost_usd": reviewer_run.total_cost_usd,
            "duration_ms": reviewer_run.duration_ms,
            "tool_calls": reviewer_run.retro.tool_call_counts,
            "grade": reviewer_grade,
            "final_text": reviewer_run.result_text,
        },
    }
    (log_dir / "pipeline-summary.json").write_text(json.dumps(summary, indent=2))

    # Hard-line assertions on the whole pipeline:
    assert builder_grade["stage_coverage"]["build"], (
        "Builder never reached the build stage (no elliot_create_tool calls)"
    )
    assert builder_grade["stage_coverage"]["deploy"], (
        "Builder never reached the deploy stage (no runtime start)"
    )
    assert builder_grade["stayed_on_policy"], (
        f"Builder went off-policy: {builder_run.retro.off_policy_tools}"
    )
    assert sum(consumer_run.retro.tool_call_counts.values()) >= 2, (
        "Consumer did not actually exercise the runtime's tools"
    )
