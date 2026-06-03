"""Layer 1 sibling — exercise Elliot's Postgres database source.

Elliot supports REST + file + Postgres + MySQL sources. The REST and file
paths are covered by ``test_layer1_mcp_protocol`` and
``test_layer1_file_sources``; this module hits the DB path end-to-end:

* Spin up an ephemeral local PostgreSQL cluster (via initdb / pg_ctl).
* Seed a schema with one parent + one child table so the SQL-FROM
  ``source_ids`` inference and JOIN behaviour are both exercised.
* Call ``elliot_discover_source`` with ``source_type="postgres"`` so the
  plugin reaches into the DB via SQLAlchemy + psycopg2.
* Define a tool that joins both tables, build, lint, and assert.

Skips automatically when PostgreSQL binaries aren't on the host (the
``ephemeral_postgres`` helper detects ``/usr/lib/postgresql/<ver>/bin``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg2
import pytest

from .helpers.local_postgres import LocalPostgres, ephemeral_postgres, postgres_available
from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

pytestmark = pytest.mark.skipif(
    not postgres_available(),
    reason="PostgreSQL binaries not on host — install postgresql-16 to enable",
)


SCHEMA_SQL = """
CREATE TABLE customers (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE NOT NULL,
    plan        TEXT NOT NULL,
    mrr_cents   INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    signed_up   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoices (
    id           BIGSERIAL PRIMARY KEY,
    customer_id  BIGINT NOT NULL REFERENCES customers(id),
    amount_cents INTEGER NOT NULL,
    status       TEXT NOT NULL,
    issued_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO customers (name, email, plan, mrr_cents, status) VALUES
    ('Alice Chen',  'alice@acme.example.com',   'enterprise', 1299000, 'active'),
    ('Bob Martinez','bob@globex.example.com',   'pro',          19900, 'active'),
    ('Carol White', 'carol@initech.example.com','enterprise',  799000, 'active'),
    ('David Park',  'david@hooli.example.com',  'starter',       2900, 'churned');

INSERT INTO invoices (customer_id, amount_cents, status) VALUES
    (1, 1299000, 'paid'),
    (1, 1299000, 'pending'),
    (2,   19900, 'paid'),
    (3,  799000, 'paid'),
    (3,  799000, 'paid');
"""


@pytest.fixture(scope="module")
def local_pg() -> Iterator[LocalPostgres]:
    with ephemeral_postgres() as pg:
        conn = psycopg2.connect(pg.dsn)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.close()
        yield pg


@pytest.fixture(scope="module")
def stack(api_base_url: str, local_pg: LocalPostgres) -> Iterator[StackEndpoints]:
    """Plugin only. Inject the DB DSN as an env var so the connector
    config can reference it via the ``{{ env:VAR }}`` template form a
    real user would use — keeps the credential out of the connector
    file the test writes to disk.
    """
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


@pytest.mark.asyncio
async def test_postgres_table_discover_round_trip(
    stack: StackEndpoints, local_pg: LocalPostgres
) -> None:
    """Discover the ``customers`` table via ``source_type=postgres`` and
    verify rows + columns. Uses ``table=...`` so the plugin issues the
    canonical ``SELECT * FROM "customers"``."""
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        res = await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "postgres",
                "config": {
                    "url": "{{ env:ELLIOT_DB_URL_E2E }}",
                    "table": "customers",
                },
                "name": "customers",
            },
        )
        assert res["row_count"] == 4, f"got {res['row_count']} customer rows"
        assert {"id", "name", "email", "plan", "mrr_cents", "status"}.issubset(set(res["columns"]))

        listed = await call_tool_json(session, "elliot_list_sources", {})
        assert any(s["name"] == "customers" for s in listed["sources"])

        sample = await call_tool_json(
            session, "elliot_sample_data", {"table_name": "customers", "limit": 10}
        )
        enterprise = [r for r in sample["rows"] if r["plan"] == "enterprise"]
        assert len(enterprise) == 2


@pytest.mark.asyncio
async def test_postgres_custom_query_then_tool_join(
    stack: StackEndpoints, local_pg: LocalPostgres
) -> None:
    """Register a DB source using a custom SELECT, then build a tool that
    joins it with another DB-source table. Proves the DB path supports
    both ``table=`` and ``query=``, and that the new source-id inference
    correctly maps two DB sources by name."""
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        # First source uses `table` (full table).
        await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "postgres",
                "config": {
                    "url": "{{ env:ELLIOT_DB_URL_E2E }}",
                    "table": "customers",
                },
                "name": "customers",
            },
        )
        # Second source uses an explicit query (filter at fetch time).
        await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "postgres",
                "config": {
                    "url": "{{ env:ELLIOT_DB_URL_E2E }}",
                    "query": (
                        "SELECT id, customer_id, amount_cents, status, issued_at "
                        "FROM invoices "
                        "WHERE status = 'paid'"
                    ),
                },
                "name": "paid_invoices",
            },
        )

        # Tool joins both materialised tables. The SQL-FROM parser should
        # attach both source IDs.
        await call_tool_json(
            session,
            "elliot_create_tool",
            {
                "name": "customer_paid_total",
                "description": (
                    "Return the total paid revenue per active customer, sorted descending."
                ),
                "category": "READ",
                "sql": (
                    "SELECT c.name, c.email, SUM(i.amount_cents) AS paid_cents "
                    'FROM "customers" c '
                    'JOIN "paid_invoices" i ON i.customer_id = c.id '
                    "WHERE c.status = 'active' "
                    "GROUP BY c.name, c.email "
                    "ORDER BY paid_cents DESC"
                ),
                "parameters": [],
            },
        )

        built = await call_tool_json(
            session,
            "elliot_build_connector",
            {"name": "DB E2E", "slug": "db-e2e"},
        )
        assert built["tool_count"] == 1
        assert built["source_count"] == 2, (
            "The tool's SQL joins both DB sources — both must be attached."
        )

        lint = await call_tool_json(session, "elliot_lint_connector", {})
        errors = [i for i in lint["issues"] if i["severity"] == "ERROR"]
        assert not errors, f"DB-source connector lint had ERRORs: {errors}"


@pytest.mark.asyncio
async def test_postgres_runtime_filter_pushdown(local_pg: LocalPostgres) -> None:
    """The connector runtime pushes a filter_groups tool's WHERE / ORDER BY /
    LIMIT straight to Postgres instead of snapshotting the whole table into
    the in-memory SQLite mirror.

    Drives ``ToolExecutor`` directly against the live ephemeral cluster so
    the push-down path (``_execute_db_pushdown`` -> ``run_select`` ->
    SQLAlchemy -> psycopg2) is exercised end-to-end against a real server.
    """
    from elliot_connector_runtime.executor import ToolExecutor
    from elliot_core.types import (
        ConnectorConfig,
        FilterCondition,
        FilterGroup,
        OrderField,
        ParameterDefinition,
        ReturnField,
        SourceConfig,
        ToolDefinition,
    )

    connector = ConnectorConfig(
        name="DB Pushdown",
        slug="db-pushdown",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="customers",
                name="customers",
                type="postgres",
                url=local_pg.dsn,
                table="customers",
            )
        ],
        tools=[
            ToolDefinition(
                id="customers_by_plan",
                name="Customers by plan",
                description="List customers on a given plan, highest revenue first.",
                category="READ",
                source_ids=["customers"],
                return_fields=[
                    ReturnField(field="name"),
                    ReturnField(field="plan"),
                    ReturnField(field="mrr_cents"),
                ],
                filter_groups=[
                    FilterGroup(
                        conditions=[
                            FilterCondition(field="plan", operator="=", parameter_name="plan")
                        ]
                    )
                ],
                order_by=[OrderField(field="mrr_cents", direction="DESC")],
                parameters=[
                    ParameterDefinition(
                        name="plan", type="string", required=True, description="Plan tier"
                    )
                ],
            )
        ],
        skills=[],
    )

    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"plan": "enterprise"})

    # SCHEMA_SQL seeds exactly two enterprise customers; the WHERE ran on the
    # server, so only those rows came back — not the whole 4-row table.
    assert len(result.rows) == 2
    assert all(r["plan"] == "enterprise" for r in result.rows)
    # ORDER BY mrr_cents DESC was pushed down too: Alice (1299000) before
    # Carol (799000).
    assert [r["name"] for r in result.rows] == ["Alice Chen", "Carol White"]

    # A different argument value re-runs the query server-side (the push-down
    # path is not served from the snapshot cache).
    starter = await executor.execute(connector.tools[0], {"plan": "starter"})
    assert [r["name"] for r in starter.rows] == ["David Park"]
