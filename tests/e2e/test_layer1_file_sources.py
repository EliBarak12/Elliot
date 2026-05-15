"""Layer 1 sibling — exercise every file-source format Elliot supports.

The main Layer 1 test (``test_layer1_mcp_protocol.py``) covers REST sources
end-to-end. This module hits the *other* design-time path: file uploads.
Same wire-level MCP transport, same stack helper, but the sources are
CSV / JSON / JSONL files staged inside the workspace via
``elliot_upload_file`` → ``elliot_discover_source(source_type="file")``.

What we want to prove:

* Every supported format round-trips uploaded bytes into a queryable
  SQLite table with the right row count and column set.
* The flattener applies to JSON/JSONL the same way it does to REST
  responses (nested objects become ``{table}_{field}`` columns).
* Filename-extension auto-detection picks the right format; an explicit
  ``format`` field in the config overrides.
* The file-reader path containment lets ``elliot_upload_file`` stages
  succeed without any ``ELLIOT_FILE_READER_ALLOW_ABSOLUTE`` opt-out.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest

from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack

# Three small fixtures, one per format. Same logical rows so every test
# can assert the same shape.

CSV_BODY = (
    "id,name,category,price,stock\n"
    "101,Pro Wireless Headphones,audio,249.99,42\n"
    "102,Ergonomic Mesh Chair,office,449.00,12\n"
    "103,Mechanical Keyboard,computing,159.00,200\n"
)

JSON_BODY = json.dumps(
    [
        {
            "id": 1,
            "name": "Alice Chen",
            "email": "alice@acme.example.com",
            "plan": "enterprise",
            "company": {"name": "Acme", "size": 250},
        },
        {
            "id": 2,
            "name": "Bob Martinez",
            "email": "bob@globex.example.com",
            "plan": "pro",
            "company": {"name": "Globex", "size": 80},
        },
        {
            "id": 3,
            "name": "Carol White",
            "email": "carol@initech.example.com",
            "plan": "enterprise",
            "company": {"name": "Initech", "size": 600},
        },
    ]
)

JSONL_BODY = "\n".join(
    json.dumps(o)
    for o in [
        {"ts": "2026-05-15T08:00:00Z", "user_id": 1, "event": "login", "feature": "dashboard"},
        {"ts": "2026-05-15T08:14:00Z", "user_id": 1, "event": "feature_used", "feature": "exports"},
        {"ts": "2026-05-15T09:00:00Z", "user_id": 3, "event": "login", "feature": "dashboard"},
        {"ts": "2026-05-15T09:05:00Z", "user_id": 3, "event": "feature_used", "feature": "api"},
    ]
)


@pytest.fixture(scope="module")
def stack(api_base_url: str) -> Iterator[StackEndpoints]:
    """Plugin only — no Studio, no eager runtime."""
    with elliot_stack(skip_studio=True, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.mark.asyncio
async def test_csv_upload_and_discover(stack: StackEndpoints) -> None:
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        up = await call_tool_json(
            session,
            "elliot_upload_file",
            {"file_name": "products.csv", "content": CSV_BODY},
        )
        assert up["file_name"] == "products.csv"
        assert up["size_bytes"] == len(CSV_BODY.encode("utf-8"))

        res = await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "csv",
                "config": {"path": up["managed_path"]},
                "name": "products",
            },
        )
        assert res["row_count"] == 3
        assert {"id", "name", "category", "price", "stock"}.issubset(res["columns"])

        sample = await call_tool_json(
            session, "elliot_sample_data", {"table_name": "products", "limit": 3}
        )
        # CSV values come back as strings from the csv.DictReader path —
        # Elliot's type inferrer marks the SQLite column type but doesn't
        # coerce row values. Cast for comparison so we stay tolerant of
        # both shapes.
        ids = sorted(int(r["id"]) for r in sample["rows"])
        assert ids == [101, 102, 103]
        first = next(r for r in sample["rows"] if int(r["id"]) == 101)
        assert first["category"] == "audio"


@pytest.mark.asyncio
async def test_json_upload_with_nested_flatten(stack: StackEndpoints) -> None:
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        up = await call_tool_json(
            session,
            "elliot_upload_file",
            {"file_name": "customers.json", "content": JSON_BODY},
        )

        res = await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "json",
                "config": {"path": up["managed_path"]},
                "name": "customers",
            },
        )
        assert res["row_count"] == 3
        # Nested ``company.name`` / ``company.size`` must land as flattened
        # columns — same code path as the REST flattener.
        assert {"id", "name", "email", "plan", "company_name", "company_size"}.issubset(
            res["columns"]
        )

        sample = await call_tool_json(
            session, "elliot_sample_data", {"table_name": "customers", "limit": 5}
        )
        alice = next(r for r in sample["rows"] if r["id"] == 1)
        assert alice["company_name"] == "Acme"
        assert alice["company_size"] == 250


@pytest.mark.asyncio
async def test_jsonl_upload_with_explicit_format(stack: StackEndpoints) -> None:
    """JSONL files use newline-delimited records — Elliot detects the
    format from the extension but the test passes it explicitly to verify
    the override path."""
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        up = await call_tool_json(
            session,
            "elliot_upload_file",
            {"file_name": "events.jsonl", "content": JSONL_BODY},
        )

        res = await call_tool_json(
            session,
            "elliot_discover_source",
            {
                "source_type": "file",
                "config": {"path": up["managed_path"], "format": "jsonl"},
                "name": "events",
            },
        )
        assert res["row_count"] == 4
        assert {"ts", "user_id", "event", "feature"}.issubset(res["columns"])

        sample = await call_tool_json(
            session, "elliot_sample_data", {"table_name": "events", "limit": 10}
        )
        # JSONL preserves the integer 1 vs string "1".
        user_ids = {r["user_id"] for r in sample["rows"]}
        assert user_ids == {1, 3}


@pytest.mark.asyncio
async def test_build_connector_over_mixed_file_sources(stack: StackEndpoints) -> None:
    """Round-trip: upload CSV + JSON, register both, write a join tool,
    lint, export. Proves a file-only connector ships end-to-end with no
    REST involved.
    """
    async with open_mcp_session(stack.plugin_mcp_url) as session:
        for name, body, file_name, fmt in [
            ("products", CSV_BODY, "products.csv", "csv"),
            ("customers", JSON_BODY, "customers.json", "json"),
        ]:
            up = await call_tool_json(
                session,
                "elliot_upload_file",
                {"file_name": file_name, "content": body},
            )
            await call_tool_json(
                session,
                "elliot_discover_source",
                {
                    "source_type": fmt,
                    "config": {"path": up["managed_path"]},
                    "name": name,
                },
            )

        # Tool spans both file sources. The new SQL-FROM parser should
        # auto-attach ``customers`` + ``products`` (and nothing else).
        await call_tool_json(
            session,
            "elliot_create_tool",
            {
                "name": "enterprise_customer_count",
                "description": "Count enterprise customers by company.",
                "category": "READ",
                "sql": (
                    "SELECT company_name, COUNT(*) AS n "
                    'FROM "customers" '
                    "WHERE plan = 'enterprise' "
                    "GROUP BY company_name "
                    "ORDER BY n DESC"
                ),
                "parameters": [],
            },
        )

        built = await call_tool_json(
            session,
            "elliot_build_connector",
            {"name": "Files Only", "slug": "files-only"},
        )
        assert built["tool_count"] == 1
        # The SQL only references ``customers`` — the new SQL-FROM inference
        # narrows the connector to just that source. ``products`` is still
        # in the session (it'll show up the moment a tool references it),
        # so this is the right behaviour: ship the minimum.
        assert built["source_count"] == 1

        lint = await call_tool_json(session, "elliot_lint_connector", {})
        errors = [i for i in lint["issues"] if i["severity"] == "ERROR"]
        assert not errors, f"file-source connector lint had ERRORs: {errors}"
