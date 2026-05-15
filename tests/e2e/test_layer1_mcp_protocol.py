"""Layer 1 E2E: drive Elliot through the MCP wire protocol, no LLM.

Speaks the same streamable-HTTP transport the Studio React app uses, so
every call here is *exactly* what an MCP client would send. This proves the
plugin's tool registration, the flattener's nested-JSON handling, the
linter, and the runtime deploy all work end-to-end across the wire.

Workflow exercised:

1. ``elliot_discover_source`` × 4   — users / products / orders / reviews
2. ``elliot_list_sources``           — 4 sources registered
3. ``elliot_sample_data``            — flattener exploded nested objects
4. ``elliot_create_tool``  × 4       — business tools spanning the 4 sources
5. ``elliot_build_connector``        — assemble
6. ``elliot_lint_connector``         — 0 ERRORs
7. ``elliot_export_connector``       — write to connectors/ dir
8. ``elliot_start_runtime``          — spawn runtime subprocess on :3001
9. Hit ``GET /v1/health`` on the runtime — connector served with N tools
10. ``elliot_stop_runtime``          — clean teardown
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints

SOURCE_DEFS = [
    ("users", "/users"),
    ("products", "/products"),
    ("orders", "/orders"),
    ("reviews", "/reviews"),
]

EXPECTED_ROWS = {"users": 6, "products": 5, "orders": 6, "reviews": 5}

# Columns the flattener must produce from the nested mock payloads. Each
# entry asserts a non-trivial part of the schema-detection path: nested
# objects (address.geo.lat → address_geo_lat), nested object inside nested
# object (reviewer.verified → reviewer_verified), object→child-table
# (orders.line_items → orders_line_items).
NESTED_COLUMNS = {
    "users": {"address_city", "address_geo_lat", "company_name", "company_industry"},
    "products": {"dimensions_width", "meta_sku"},
    "orders": {"billing_address_city"},
    "reviews": {"reviewer_id", "reviewer_verified"},
}

# Four business tools spanning all 4 sources. Each is a real, useful query
# you'd build for an e-commerce ops dashboard.
BUSINESS_TOOLS = [
    {
        "name": "list_active_enterprise_customers",
        "description": ("List active customers on the enterprise plan, sorted by MRR descending."),
        "category": "READ",
        "sql": (
            "SELECT id, name, email, mrr, company_name "
            'FROM "users" '
            "WHERE plan = 'enterprise' AND status = 'active' "
            "ORDER BY mrr DESC"
        ),
        "parameters": [],
    },
    {
        "name": "top_products_by_revenue",
        "description": (
            "Return the top N products by total revenue from fulfilled orders. "
            "Joins orders_line_items against products."
        ),
        "category": "READ",
        "sql": (
            "SELECT p.id, p.title, p.category, "
            "SUM(li.quantity * li.unit_price) AS revenue "
            'FROM "products" p '
            'JOIN "orders_line_items" li ON li.product_id = p.id '
            'JOIN "orders" o ON li._parent_id = o.rowid '
            "WHERE o.status = 'fulfilled' "
            "GROUP BY p.id, p.title, p.category "
            "ORDER BY revenue DESC "
            "LIMIT :limit"
        ),
        "parameters": [
            {
                "name": "limit",
                "type": "integer",
                "required": False,
                "description": "max products to return (default 5)",
                "default": 5,
            }
        ],
    },
    {
        "name": "customer_order_history",
        "description": "All orders for a given customer, newest first.",
        "category": "READ",
        "sql": (
            "SELECT id, status, total, created_at "
            'FROM "orders" '
            "WHERE customer_id = :customer_id "
            "ORDER BY created_at DESC"
        ),
        "parameters": [
            {
                "name": "customer_id",
                "type": "integer",
                "required": True,
                "description": "customer ID from /users",
            }
        ],
    },
    {
        "name": "pending_reviews_with_low_rating",
        "description": (
            "Reviews with rating ≤ 3 that the team has not yet responded to — "
            "the inbox of complaints to action."
        ),
        "category": "READ",
        "sql": (
            "SELECT r.id, r.product_id, r.rating, r.title, r.reviewer_name "
            'FROM "reviews" r '
            "WHERE r.rating <= :max_rating AND r.response_author IS NULL "
            "ORDER BY r.rating ASC, r.created_at DESC"
        ),
        "parameters": [
            {
                "name": "max_rating",
                "type": "integer",
                "required": False,
                "description": "Treat ratings ≤ this as needing attention (default 3)",
                "default": 3,
            }
        ],
    },
]


@pytest.fixture(scope="module")
def stack(api_base_url: str):  # type: ignore[no-untyped-def]
    """Layer 1 needs plugin only — agent never runs, Studio not needed."""
    import os

    from .helpers.stack import elliot_stack

    with elliot_stack(skip_studio=True, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.mark.asyncio
async def test_full_workflow_via_mcp_wire_protocol(
    stack: StackEndpoints, api_base_url: str
) -> None:
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        # ── 0. Tool registry ────────────────────────────────────────────────
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}
        required = {
            "elliot_discover_source",
            "elliot_list_sources",
            "elliot_sample_data",
            "elliot_create_tool",
            "elliot_build_connector",
            "elliot_lint_connector",
            "elliot_export_connector",
            "elliot_run_eval",
            "elliot_start_runtime",
            "elliot_stop_runtime",
        }
        missing = required - tool_names
        assert not missing, f"Elliot plugin is missing expected MCP tools: {missing}"

        # ── 1. Discover the 4 nested REST sources ──────────────────────────
        for name, path in SOURCE_DEFS:
            res = await call_tool_json(
                session,
                "elliot_discover_source",
                {
                    "source_type": "rest",
                    "config": {"url": f"{api_base_url}{path}"},
                    "name": name,
                },
            )
            assert res["row_count"] == EXPECTED_ROWS[name], (
                f"Wrong row count for {name}: got {res['row_count']}"
            )
            columns = set(res["columns"])
            expected = NESTED_COLUMNS[name]
            assert expected.issubset(columns), (
                f"Flattener missed nested columns for {name}. Expected {expected}, got {columns}"
            )

        # ── 2. List sources — all 4 must appear ─────────────────────────────
        listed = await call_tool_json(session, "elliot_list_sources", {})
        listed_names = {s["name"] for s in listed["sources"]}
        assert listed_names == set(EXPECTED_ROWS), (
            f"elliot_list_sources returned {listed_names}, expected {set(EXPECTED_ROWS)}"
        )

        # ── 3. Sample data — verify nested rows landed in SQLite ────────────
        users_sample = await call_tool_json(
            session, "elliot_sample_data", {"table_name": "users", "limit": 2}
        )
        assert users_sample["rows"], "users sample is empty"
        first = users_sample["rows"][0]
        # Nested address.geo.lat must be reachable as a flat column.
        assert "address_geo_lat" in first, (
            "Expected flattened nested column 'address_geo_lat' missing — "
            "the flattener didn't process address.geo."
        )

        # ── 4. Define the 4 business tools ─────────────────────────────────
        for tool in BUSINESS_TOOLS:
            res = await call_tool_json(session, "elliot_create_tool", tool)
            assert res.get("status") == "created", f"create_tool failed: {res}"

        # ── 5. Build the connector ─────────────────────────────────────────
        built = await call_tool_json(
            session,
            "elliot_build_connector",
            {
                "name": "E-Commerce Ops",
                "slug": "ecommerce-ops",
                "description": "Customer / product / order / review analytics across 4 APIs",
            },
        )
        assert built["tool_count"] == len(BUSINESS_TOOLS)
        assert built["source_count"] == len(SOURCE_DEFS)

        # ── 6. Lint — zero ERROR-severity issues ──────────────────────────
        lint = await call_tool_json(session, "elliot_lint_connector", {})
        errors = [i for i in lint["issues"] if i["severity"] == "ERROR"]
        assert not errors, f"Lint reported {len(errors)} ERROR issues:\n" + "\n".join(
            f"  - {i['code']}: {i['message']}" for i in errors
        )

        # ── 7. Export to the workspace's connectors dir ────────────────────
        connector_path = stack.workspace / "connectors" / "ecommerce-ops.connector.json"
        exported = await call_tool_json(
            session, "elliot_export_connector", {"path": str(connector_path)}
        )
        assert exported.get("status") in {"exported", "ok"} or "path" in exported
        assert connector_path.exists(), "Exported connector file is missing on disk"
        config = json.loads(connector_path.read_text())
        assert config["slug"] == "ecommerce-ops"
        assert len(config["tools"]) == len(BUSINESS_TOOLS)
        assert len(config["sources"]) == len(SOURCE_DEFS)

        # ── 8. Spin up the runtime over this connector ─────────────────────
        runtime_port = 3001
        started = await call_tool_json(
            session,
            "elliot_start_runtime",
            {"port": runtime_port, "connector_path": str(connector_path)},
        )
        assert started.get("status") in {"running", "already_running"}, (
            f"runtime did not come up cleanly: {started}"
        )

        # ── 9. Hit the runtime's /v1/health — connector + tool counts ──────
        try:
            health = httpx.get(f"http://127.0.0.1:{runtime_port}/v1/health", timeout=10).json()
            assert health["connector"]["slug"] == "ecommerce-ops"
            assert health["connector"]["tool_count"] == len(BUSINESS_TOOLS)
            assert health["connector"]["source_count"] == len(SOURCE_DEFS)
        finally:
            # ── 10. Teardown — leave the runtime port free for later modules
            await call_tool_json(session, "elliot_stop_runtime", {})


@pytest.mark.asyncio
async def test_eval_suite_runs_against_built_connector(
    stack: StackEndpoints, api_base_url: str
) -> None:
    """Smaller scope: re-build a connector, write an eval suite, run it via MCP."""
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        # Re-use the session state from the first test if it persisted;
        # otherwise lay down enough to run an eval.
        sources = await call_tool_json(session, "elliot_list_sources", {})
        if not sources["sources"]:
            for name, path in SOURCE_DEFS[:1]:
                await call_tool_json(
                    session,
                    "elliot_discover_source",
                    {
                        "source_type": "rest",
                        "config": {"url": f"{api_base_url}{path}"},
                        "name": name,
                    },
                )

        tools = await call_tool_json(session, "elliot_list_tools", {})
        if not tools["tools"]:
            await call_tool_json(session, "elliot_create_tool", BUSINESS_TOOLS[0])
            await call_tool_json(
                session,
                "elliot_build_connector",
                {"name": "Eval Test", "slug": "eval-test"},
            )

        # Write a small JSON eval suite to .elliot/eval/<suite_id>.json.
        suite_id = "ecommerce-ops-smoke"
        eval_dir = Path(stack.workspace) / ".elliot" / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / f"{suite_id}.json").write_text(
            json.dumps(
                {
                    "id": suite_id,
                    "name": "E-Commerce Ops smoke",
                    "cases": [
                        {
                            "id": "enterprise-customers-non-empty",
                            "tool_id": "list_active_enterprise_customers",
                            "params": {},
                            "match_mode": "shape",
                        }
                    ],
                }
            )
        )

        result = await call_tool_json(session, "elliot_run_eval", {"suite_id": suite_id})
        # The runner returns an EvalRunResult-shaped dict: ``passed`` + ``failed``
        # are case counts, ``score`` is in [0,1]. We just need it to have run
        # the case end-to-end without an executor error.
        assert "score" in result, f"eval didn't run: {result}"
