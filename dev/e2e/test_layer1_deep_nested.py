"""Layer 1 sibling — exercise the flattener against a deeply nested JSON.

A real user reported losing parent linkage on auto-flattened child
tables: when a JSON has nested arrays of objects with NO natural foreign
key (e.g. ``insights[].teaserblocks[]``), the flattener produces a
``insights_teaserblocks`` table that can't be joined back to its parent.
This test reproduces that case at four levels of depth and asserts every
child level can be joined back to its parent through ``_parent_id`` →
``_id``.

The fixture uses zero natural foreign keys between levels:
companies → departments → teams → members → skills (primitives). The
only way for a tool to ask "how many members per company" is to walk the
flattener-injected linkage columns.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest

from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

# Three companies, six departments total, eleven teams, twenty members.
# No level carries a natural FK to its parent — only structural nesting.
DEEP_DATA = [
    {
        "id": "co_acme",
        "name": "Acme",
        "tier": "enterprise",
        "departments": [
            {
                "name": "Engineering",
                "teams": [
                    {
                        "name": "Platform",
                        "members": [
                            {"login": "alice", "skills": ["python", "postgres"]},
                            {"login": "ben", "skills": ["go", "redis"]},
                            {"login": "cara", "skills": ["python", "kubernetes"]},
                        ],
                    },
                    {
                        "name": "ML",
                        "members": [
                            {"login": "dan", "skills": ["python", "pytorch"]},
                            {"login": "elena", "skills": ["rust", "cuda"]},
                        ],
                    },
                ],
            },
            {
                "name": "Operations",
                "teams": [
                    {
                        "name": "SRE",
                        "members": [
                            {"login": "fran", "skills": ["terraform", "aws"]},
                            {"login": "guille", "skills": ["incident-mgmt", "tracing"]},
                        ],
                    },
                ],
            },
        ],
    },
    {
        "id": "co_initech",
        "name": "Initech",
        "tier": "enterprise",
        "departments": [
            {
                "name": "Engineering",
                "teams": [
                    {
                        "name": "Data",
                        "members": [
                            {"login": "han", "skills": ["spark", "sql"]},
                            {"login": "irene", "skills": ["dbt", "looker"]},
                            {"login": "jack", "skills": ["python", "airflow"]},
                        ],
                    },
                ],
            },
            {
                "name": "Sales",
                "teams": [
                    {
                        "name": "Mid-Market",
                        "members": [
                            {"login": "kira", "skills": ["forecasting"]},
                            {"login": "leo", "skills": ["negotiation"]},
                        ],
                    },
                    {
                        "name": "Enterprise",
                        "members": [
                            {"login": "maya", "skills": ["enterprise-sales"]},
                        ],
                    },
                ],
            },
        ],
    },
    {
        "id": "co_umbrella",
        "name": "Umbrella",
        "tier": "enterprise",
        "departments": [
            {
                "name": "R&D",
                "teams": [
                    {
                        "name": "Bio",
                        "members": [
                            {"login": "naomi", "skills": ["biology"]},
                            {"login": "owen", "skills": ["genomics"]},
                            {"login": "petra", "skills": ["python"]},
                        ],
                    },
                    {
                        "name": "Robotics",
                        "members": [
                            {"login": "quinn", "skills": ["ros", "cpp"]},
                            {"login": "ravi", "skills": ["control-systems"]},
                        ],
                    },
                ],
            },
        ],
    },
]


# Header counts derived from the fixture. Update if you change DEEP_DATA.
EXPECTED_COMPANIES = 3
EXPECTED_DEPARTMENTS = 5  # Acme:2 + Initech:2 + Umbrella:1
EXPECTED_TEAMS = 8  # Acme:2+1 + Initech:1+2 + Umbrella:2
EXPECTED_MEMBERS = 18  # Acme:3+2+2 + Initech:3+2+1 + Umbrella:3+2
EXPECTED_MEMBERS_PER_COMPANY = {"Acme": 7, "Initech": 6, "Umbrella": 5}


@pytest.fixture(scope="module")
def stack(api_base_url: str) -> Iterator[StackEndpoints]:
    with elliot_stack(skip_studio=True, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.fixture(scope="module")
def discovered(stack: StackEndpoints) -> StackEndpoints:
    """Upload the deep JSON and run elliot_discover_source once for the
    whole module — the assertions in each test query the same materialized
    data."""
    import asyncio

    async def _seed() -> None:
        async with open_mcp_session(stack.plugin_mcp_url) as session:
            up = await call_tool_json(
                session,
                "elliot_upload_file",
                {
                    "file_name": "companies.json",
                    "content": json.dumps(DEEP_DATA),
                },
            )
            await call_tool_json(
                session,
                "elliot_discover_source",
                {
                    "source_type": "json",
                    "config": {"path": up["managed_path"]},
                    "name": "companies",
                },
            )

    asyncio.run(_seed())
    return stack


@pytest.mark.asyncio
async def test_flatten_produces_one_table_per_level(
    discovered: StackEndpoints,
) -> None:
    """The flattener must materialize each nested array as its own
    SQLite table named ``{parent}_{field}``."""
    async with open_mcp_session(discovered.plugin_mcp_url) as session:
        tables = await call_tool_json(session, "elliot_list_tables", {})
        names = set(tables["tables"])
        # Each nesting level → its own table.
        assert {
            "companies",
            "companies_departments",
            "companies_departments_teams",
            "companies_departments_teams_members",
        }.issubset(names), f"missing flattener-produced child tables; got {names}"


@pytest.mark.asyncio
async def test_each_child_table_keeps_id_and_parent_id_linkage(
    discovered: StackEndpoints,
) -> None:
    """Every flattener-produced child row must carry:

    * ``_id`` — a unique row identifier within the child table
    * ``_parent_id`` — the ``_id`` of the parent row in the table one level up

    Without this the fixture (which has no natural FK between levels)
    cannot be joined back together. Real users hit this with deeply-
    nested JSON like ``insights[].teaserblocks[]``."""
    async with open_mcp_session(discovered.plugin_mcp_url) as session:
        # Sanity: row counts at each level match the fixture.
        for table, expected in [
            ("companies", EXPECTED_COMPANIES),
            ("companies_departments", EXPECTED_DEPARTMENTS),
            ("companies_departments_teams", EXPECTED_TEAMS),
            ("companies_departments_teams_members", EXPECTED_MEMBERS),
        ]:
            count = await call_tool_json(
                session, "elliot_query_sql", {"sql": f'SELECT COUNT(*) AS n FROM "{table}"'}
            )
            assert count["rows"][0]["n"] == expected, f"{table}: {count}"

        # Linkage check: every child row's _parent_id must reference an
        # existing parent _id. Run the join — if linkage is dropped, the
        # JOIN returns zero rows.
        joined = await call_tool_json(
            session,
            "elliot_query_sql",
            {
                "sql": (
                    "SELECT COUNT(*) AS n "
                    'FROM "companies_departments" d '
                    'JOIN "companies" c ON c._id = d._parent_id'
                )
            },
        )
        assert joined["rows"][0]["n"] == EXPECTED_DEPARTMENTS, (
            "departments are orphaned — _parent_id linkage to companies is broken"
        )


@pytest.mark.asyncio
async def test_full_four_level_join_aggregation(
    discovered: StackEndpoints,
) -> None:
    """The real-world test: a tool that walks all four levels of nesting
    and answers "how many members does each company have?" — only
    possible if the flattener kept linkage at every level."""
    async with open_mcp_session(discovered.plugin_mcp_url) as session:
        await call_tool_json(
            session,
            "elliot_create_tool",
            {
                "name": "members_per_company",
                "description": (
                    "Return total member headcount per company, walking "
                    "departments → teams → members through flattener-injected "
                    "_parent_id linkage."
                ),
                "category": "READ",
                "sql": (
                    "SELECT c.name AS company, COUNT(m._id) AS members "
                    'FROM "companies" c '
                    'JOIN "companies_departments" d '
                    "  ON d._parent_id = c._id "
                    'JOIN "companies_departments_teams" t '
                    "  ON t._parent_id = d._id "
                    'JOIN "companies_departments_teams_members" m '
                    "  ON m._parent_id = t._id "
                    "GROUP BY c.name "
                    "ORDER BY members DESC"
                ),
                "parameters": [],
            },
        )

        await call_tool_json(
            session,
            "elliot_build_connector",
            {"name": "Companies Deep", "slug": "companies-deep"},
        )

        # Execute the tool via the in-process executor (no need to spawn a
        # runtime — the engine already holds the materialized tables).
        sample = await call_tool_json(
            session,
            "elliot_query_sql",
            {
                "sql": (
                    "SELECT c.name AS company, COUNT(m._id) AS members "
                    'FROM "companies" c '
                    'JOIN "companies_departments" d ON d._parent_id = c._id '
                    'JOIN "companies_departments_teams" t ON t._parent_id = d._id '
                    'JOIN "companies_departments_teams_members" m ON m._parent_id = t._id '
                    "GROUP BY c.name "
                    "ORDER BY members DESC"
                )
            },
        )
        actual = {r["company"]: r["members"] for r in sample["rows"]}
        assert actual == EXPECTED_MEMBERS_PER_COMPANY, (
            f"four-level JOIN wrong; got {actual}, expected {EXPECTED_MEMBERS_PER_COMPANY}"
        )
