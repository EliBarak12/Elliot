"""Layer 1 sibling — exercise Elliot's MySQL database source.

Counterpart to ``test_layer1_db_sources.py`` (which targets Postgres).
Spins up an ephemeral MariaDB cluster via ``mariadb-install-db`` +
``mariadbd``, seeds a schema, and drives the canonical
``elliot_discover_source`` → ``elliot_create_tool`` → lint cycle through
the MCP wire protocol. Verifies that ``source_type="mysql"`` reaches the
DB via SQLAlchemy + ``pymysql`` and that the SQL-FROM source-id
inference works the same way it does for Postgres.

Skips gracefully when ``mariadbd`` isn't on the host (i.e. neither
``mysql-server`` nor ``mariadb-server`` is installed).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pymysql
import pytest

from .helpers.local_mysql import LocalMySQL, ephemeral_mysql, mysql_available
from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

pytestmark = pytest.mark.skipif(
    not mysql_available(),
    reason="MySQL / MariaDB binaries not on host — install mariadb-server to enable",
)


SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE accounts (
        id          BIGINT PRIMARY KEY AUTO_INCREMENT,
        name        VARCHAR(120) NOT NULL,
        email       VARCHAR(200) UNIQUE NOT NULL,
        tier        VARCHAR(40)  NOT NULL,
        mrr_cents   INT          NOT NULL,
        status      VARCHAR(20)  NOT NULL DEFAULT 'active'
    )
    """,
    """
    CREATE TABLE tickets (
        id           BIGINT PRIMARY KEY AUTO_INCREMENT,
        account_id   BIGINT NOT NULL,
        subject      VARCHAR(200) NOT NULL,
        priority     VARCHAR(20) NOT NULL,
        status       VARCHAR(20) NOT NULL,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    )
    """,
    """
    INSERT INTO accounts (name, email, tier, mrr_cents, status) VALUES
        ('Acme Corp',  'billing@acme.example.com',    'enterprise', 1299000, 'active'),
        ('Globex',     'ops@globex.example.com',      'pro',          19900, 'active'),
        ('Initech',    'finance@initech.example.com', 'enterprise',  799000, 'active'),
        ('Hooli',      'ops@hooli.example.com',       'starter',       2900, 'churned')
    """,
    """
    INSERT INTO tickets (account_id, subject, priority, status) VALUES
        (1, 'Slow report export',     'high',   'open'),
        (1, 'Add SSO',                'medium', 'open'),
        (2, 'Pricing question',       'low',    'resolved'),
        (3, 'Outage 2026-05-10',      'urgent', 'resolved'),
        (3, 'Quarterly review prep',  'medium', 'open')
    """,
]


@pytest.fixture(scope="module")
def local_my() -> Iterator[LocalMySQL]:
    with ephemeral_mysql(database="elliot_e2e_my") as my:
        conn = pymysql.connect(
            host=my.host, port=my.port, user=my.user, database=my.database, autocommit=True
        )
        with conn.cursor() as cur:
            for stmt in SCHEMA_STATEMENTS:
                cur.execute(stmt)
        conn.close()
        yield my


@pytest.fixture(scope="module")
def stack(api_base_url: str, local_my: LocalMySQL) -> Iterator[StackEndpoints]:
    """Inject the MySQL DSN as an env var so the connector references it
    via the ``{{ env:VAR }}`` template form a real user would use."""
    with elliot_stack(
        skip_studio=True,
        skip_runtime=True,
        extra_env={
            "ELLIOT_MYSQL_URL_E2E": local_my.dsn,
            "ELLIOT_SECRET_ELLIOT_MYSQL_URL_E2E": local_my.dsn,
        },
    ) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.mark.asyncio
async def test_mysql_table_discover_round_trip(stack: StackEndpoints, local_my: LocalMySQL) -> None:
    """Discover ``accounts`` via ``source_type=mysql`` + ``table=``."""
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        res = await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "mysql",
                "config": {
                    "url": "{{ env:ELLIOT_MYSQL_URL_E2E }}",
                    "table": "accounts",
                },
                "name": "accounts",
            },
        )
        assert res["row_count"] == 4, f"got {res['row_count']} account rows"
        assert {"id", "name", "email", "tier", "mrr_cents", "status"}.issubset(set(res["columns"]))

        listed = await call_tool_json(session, "elliot_list_sources", {})
        assert any(s["name"] == "accounts" and s["type"] == "mysql" for s in listed["sources"])

        sample = await call_tool_json(
            session, "elliot_sample_data", {"table_name": "accounts", "limit": 10}
        )
        enterprise = [r for r in sample["rows"] if r["tier"] == "enterprise"]
        assert len(enterprise) == 2


@pytest.mark.asyncio
async def test_mysql_join_tool_lint_clean(stack: StackEndpoints, local_my: LocalMySQL) -> None:
    """Register two MySQL sources and build a tool that joins them.
    Confirms the SQL-FROM inference handles cross-source joins for MySQL
    the same way it does for Postgres."""
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "mysql",
                "config": {
                    "url": "{{ env:ELLIOT_MYSQL_URL_E2E }}",
                    "table": "accounts",
                },
                "name": "accounts",
            },
        )
        await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "mysql",
                "config": {
                    "url": "{{ env:ELLIOT_MYSQL_URL_E2E }}",
                    "query": (
                        "SELECT id, account_id, subject, priority, status "
                        "FROM tickets "
                        "WHERE status = 'open'"
                    ),
                },
                "name": "open_tickets",
            },
        )

        await call_tool_json(
            session,
            "elliot_create_tool",
            {
                "name": "enterprise_open_ticket_load",
                "description": ("Return per-account open-ticket counts for enterprise customers."),
                "category": "READ",
                "sql": (
                    "SELECT a.name, a.email, COUNT(t.id) AS open_tickets "
                    'FROM "accounts" a '
                    'LEFT JOIN "open_tickets" t ON t.account_id = a.id '
                    "WHERE a.tier = 'enterprise' AND a.status = 'active' "
                    "GROUP BY a.name, a.email "
                    "ORDER BY open_tickets DESC"
                ),
                "parameters": [],
            },
        )

        built = await call_tool_json(
            session,
            "elliot_build_connector",
            {"name": "MySQL E2E", "slug": "mysql-e2e"},
        )
        assert built["tool_count"] == 1
        assert built["source_count"] == 2, (
            "Tool JOINs both MySQL sources — inference should attach both."
        )

        lint = await call_tool_json(session, "elliot_lint_connector", {})
        errors = [i for i in lint["issues"] if i["severity"] == "ERROR"]
        assert not errors, f"MySQL-source connector lint had ERRORs: {errors}"
