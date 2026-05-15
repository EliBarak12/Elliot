"""Layer 2 sibling — real Claude Code agent builds a connector over a
heterogeneous source mix (file + Postgres), not just REST.

The main multi-agent pipeline (``test_layer2_claude_agent``) proves the
agent loop works against REST sources with pagination, auth, and deep
nesting. This module proves the same loop works when the connector
includes:

* A **file source** (CSV staged via ``elliot_upload_file``)
* A **Postgres database source** (ephemeral cluster via the local-pg
  helper, talked to with ``source_type=postgres`` + ``{{ env:... }}`` DSN)

The agent's job: build one connector across both, lint it, deploy the
runtime, then a consumer agent uses the deployed tools to answer a
business question that requires joining file data and DB data through
the runtime's SQLite materialization.

Run cost is small (~$0.30-0.50 builder + ~$0.05 consumer) and skipped
gracefully when either Claude Code or PostgreSQL is missing on the host.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator

import httpx
import psycopg2
import pytest

from .helpers.agent_retrospective import to_markdown
from .helpers.claude_agent import AgentRun, claude_is_available, run_claude_agent
from .helpers.local_postgres import LocalPostgres, ephemeral_postgres, postgres_available
from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

pytestmark = [
    pytest.mark.skipif(
        not claude_is_available(),
        reason="claude CLI not on PATH",
    ),
    pytest.mark.skipif(
        not postgres_available(),
        reason="PostgreSQL binaries not on host",
    ),
]


# A small product catalog staged as a CSV file in the workspace.
CATALOG_CSV = (
    "sku,name,category,unit_price\n"
    "SKU-AUD-001,Pro Wireless Headphones,audio,249.99\n"
    "SKU-OFF-002,Ergonomic Mesh Chair,office,449.00\n"
    "SKU-OFF-003,Standing Desk Converter,office,299.00\n"
    "SKU-COM-004,Mechanical Keyboard 75%,computing,159.00\n"
    "SKU-COM-005,4K Webcam Pro,computing,199.99\n"
)


# A purchase-orders table that references SKUs from the file.
ORDERS_SCHEMA = """
CREATE TABLE purchase_orders (
    id            BIGSERIAL PRIMARY KEY,
    sku           TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    status        TEXT NOT NULL,
    placed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO purchase_orders (sku, quantity, status) VALUES
    ('SKU-AUD-001', 2, 'fulfilled'),
    ('SKU-OFF-002', 1, 'fulfilled'),
    ('SKU-OFF-002', 3, 'pending'),
    ('SKU-OFF-003', 1, 'cancelled'),
    ('SKU-COM-004', 5, 'fulfilled'),
    ('SKU-COM-005', 1, 'fulfilled'),
    ('SKU-AUD-001', 1, 'pending');
"""


@pytest.fixture(scope="module")
def local_pg() -> Iterator[LocalPostgres]:
    with ephemeral_postgres(database="elliot_e2e_mix") as pg:
        conn = psycopg2.connect(pg.dsn)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(ORDERS_SCHEMA)
        conn.close()
        yield pg


@pytest.fixture(scope="module")
def stack(api_base_url: str, local_pg: LocalPostgres) -> Iterator[StackEndpoints]:
    """Plugin only. Inject the DB DSN via ``ELLIOT_DB_URL_E2E`` so the
    agent can reference it as ``{{ env:ELLIOT_DB_URL_E2E }}`` in the
    connector — the same pattern a real user would use."""
    with elliot_stack(
        skip_studio=True,
        skip_runtime=True,
        extra_env={
            "ELLIOT_DB_URL_E2E": local_pg.dsn,
            "ELLIOT_SECRET_ELLIOT_DB_URL_E2E": local_pg.dsn,
        },
    ) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


BUILDER_PROMPT = """\
You are the **builder** agent. Use only the Elliot MCP tools
(mcp__elliot__*).

Build an MCP connector that spans **two source types simultaneously**:

1. A CSV file containing the product catalog. Stage it first:
     elliot_upload_file(file_name="catalog.csv", content="<CSV body below>")
   then register it:
     elliot_discover_source(source_type="csv",
                            config={{"path": <managed_path from upload>}},
                            name="catalog")

   The CSV body is:
{csv_body}

2. A Postgres database holding purchase orders. The DSN is exposed via
   the env var ``ELLIOT_DB_URL_E2E``. Register it as:
     elliot_discover_source(
       source_type="postgres",
       config={{"url": "{{{{ env:ELLIOT_DB_URL_E2E }}}}",
               "table": "purchase_orders"}},
       name="purchase_orders",
     )
   (literal ``{{ env:VAR }}`` double-brace template form, NOT a bare name.)

Then create **two tools** via elliot_create_tool:

- ``top_skus_by_fulfilled_quantity`` (READ): JOIN catalog × purchase_orders,
  filter ``status = 'fulfilled'``, sum quantity per SKU, return top N.
  Parameters: ``limit`` integer optional default 5.

- ``pending_orders_with_product_info`` (READ): purchase_orders rows where
  ``status = 'pending'``, joined to catalog so the result includes the
  product name and unit price. No parameters.

Tool-SQL conventions (important):
- Reference parameters as ``:param_name`` (SQLite-style colon prefix), NOT
  ``{{{{ param_name }}}}`` (Jinja) — the runtime engine rejects Jinja
  syntax and the consumer will see a SQL parser error at call time.
- Tables already exist with the source ``name`` you registered (``catalog``,
  ``purchase_orders``); quote them with double quotes when referencing.

After both tools exist:
  - elliot_build_connector name="Mixed Sources" slug="mixed-sources"
  - elliot_lint_connector  (confirm zero ERROR-severity issues)
  - elliot_export_connector path="connectors/mixed-sources.connector.json"
  - elliot_start_runtime port=3001

When done, reply with exactly one JSON line:
  {{"sources": N, "tools": M, "lint_errors": K, "runtime": "running"}}
""".strip()


CONSUMER_PROMPT = """\
You are an **inventory analyst**. The MCP tools (mcp__mixed__*) span a
product catalog and a purchase-orders DB.

Question: **What are the top 3 SKUs by fulfilled quantity, including the
product name and unit price?** Also list any currently-pending orders.

Steps:
1. Call ``mcp__mixed__top_skus_by_fulfilled_quantity(limit=3)``.
2. Call ``mcp__mixed__pending_orders_with_product_info``.
3. Write a short Markdown report. End with one line:
     RESULT: top_sku=<sku>
""".strip()


def _write_retro(run: AgentRun, dest, title: str) -> None:
    dest.write_text(to_markdown(run.retro, title=title), encoding="utf-8")


@pytest.mark.asyncio
async def test_agent_builds_mixed_source_connector(stack: StackEndpoints) -> None:
    log_dir = stack.log_dir
    builder_budget = float(os.environ.get("ELLIOT_E2E_BUILDER_BUDGET_USD", "3.00"))
    consumer_budget = float(os.environ.get("ELLIOT_E2E_CONSUMER_BUDGET_USD", "1.50"))

    builder_run = run_claude_agent(
        BUILDER_PROMPT.format(csv_body=CATALOG_CSV),
        mcp_url=stack.plugin_mcp_url,
        workspace=stack.workspace,
        role="builder",
        server_name="elliot",
        max_budget_usd=builder_budget,
        timeout_seconds=900,
    )
    _write_retro(builder_run, log_dir / "retro-builder-mixed.md", "Builder (file+DB) retrospective")
    assert builder_run.succeeded, (
        f"Builder failed (exit={builder_run.exit_code}, "
        f"cost=${builder_run.total_cost_usd:.2f}). Last: {builder_run.result_text!r}"
    )

    # Independent verification of the builder's work via MCP.
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        sources = await call_tool_json(session, "elliot_list_sources", {})
        names = {s["name"] for s in sources["sources"]}
        assert {"catalog", "purchase_orders"}.issubset(names), (
            f"Builder did not register both sources; got {names}"
        )
        types = {s["name"]: s["type"] for s in sources["sources"]}
        assert types["catalog"] == "file"
        assert types["purchase_orders"] == "postgres"

        info = await call_tool_json(session, "studio_get_connector_info", {})
        assert info.get("connector_built") is True
        connector = info.get("connector") or {}
        assert connector.get("slug") == "mixed-sources"

        lint = await call_tool_json(session, "elliot_lint_connector", {})
        errors = [i for i in lint["issues"] if i["severity"] == "ERROR"]
        assert not errors, f"Builder left {len(errors)} lint ERRORs"

    # Runtime must be alive on :3001 with the connector loaded.
    health = httpx.get("http://127.0.0.1:3001/v1/health", timeout=10).json()
    assert health["connector"]["slug"] == "mixed-sources"
    assert health["connector"]["source_count"] >= 2

    # ── Consumer phase ────────────────────────────────────────────────────
    consumer_run = run_claude_agent(
        CONSUMER_PROMPT,
        mcp_url="http://127.0.0.1:3001/mcp/",
        workspace=stack.workspace,
        role="consumer",
        server_name="mixed",
        max_budget_usd=consumer_budget,
        timeout_seconds=600,
    )
    _write_retro(
        consumer_run,
        log_dir / "retro-consumer-mixed.md",
        "Consumer (file+DB) retrospective",
    )
    assert consumer_run.succeeded, (
        f"Consumer failed (exit={consumer_run.exit_code}, "
        f"cost=${consumer_run.total_cost_usd:.2f}). Last: {consumer_run.result_text!r}"
    )
    # Consumer must have actually exercised the runtime — both tools at least once.
    used = {
        t.removeprefix("mcp__mixed__")
        for t in consumer_run.retro.tool_call_counts
        if t.startswith("mcp__mixed__")
    }
    assert "top_skus_by_fulfilled_quantity" in used, (
        f"Consumer never called the cross-source tool; used={used}"
    )

    # Tear the runtime down so the next module doesn't port-collide.
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        with contextlib.suppress(AssertionError):
            await call_tool_json(session, "elliot_stop_runtime", {})

    summary = {
        "builder": {
            "cost_usd": builder_run.total_cost_usd,
            "turns": builder_run.num_turns,
            "tool_calls": builder_run.retro.tool_call_counts,
        },
        "consumer": {
            "cost_usd": consumer_run.total_cost_usd,
            "turns": consumer_run.num_turns,
            "tool_calls": consumer_run.retro.tool_call_counts,
            "final_text": consumer_run.result_text,
        },
    }
    (log_dir / "pipeline-summary-mixed.json").write_text(json.dumps(summary, indent=2))
