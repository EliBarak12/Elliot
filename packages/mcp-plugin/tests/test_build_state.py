"""Freshness + trust-fix tests: lint/scan on CURRENT state, F5 refresh, F3 upsert,
and the list-tool token diet."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from elliot_core.mcp_compat import FastMCP

from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
from elliot_mcp_plugin.tools.eval_tools import register_eval_tools
from elliot_mcp_plugin.tools.onboarding_tools import register_onboarding_tools
from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
from elliot_mcp_plugin.tools.source_tools import register_source_tools
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_source_tools(server, session)
    register_tool_tools(server, session)
    register_skill_tools(server, session)
    register_connector_tools(server, session)
    register_eval_tools(server, session)
    register_onboarding_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):  # type: ignore[no-untyped-def]
    fn = mcp._tool_manager._tools[name].fn
    if inspect.iscoroutinefunction(fn):

        def sync_wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            return asyncio.run(fn(*args, **kwargs))

        return sync_wrapper
    return fn


def _setup_source_and_tool(mcp: FastMCP, tmp_path: Path) -> None:
    p = tmp_path / "orders.csv"
    p.write_text("id,amount\n1,100\n2,200\n3,300\n")
    _tool(mcp, "elliot_discover_source")(source_type="file", config={"path": str(p)}, name="orders")
    out = _tool(mcp, "elliot_create_tool")(
        name="list_orders",
        description="List orders with their amounts for review.",
        category="READ",
        sql='SELECT id, amount FROM "orders" LIMIT 10',
        parameters=[],
    )
    assert out.get("tool_id") == "list_orders", out


# ── F5: mutations refresh the built connector ────────────────────────────────


def test_update_tool_refreshes_built_connector(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_build_connector")(name="Orders", slug="orders")
    assert session.connector is not None
    old_build_id = session.build_id

    new_desc = "List every order row with id and amount for auditors."
    out = _tool(mcp, "elliot_update_tool")(tool_id="list_orders", patch={"description": new_desc})
    assert out.get("status") == "updated"
    # The built snapshot now carries the NEW definition — previously it kept
    # the old one and export/publish silently shipped stale contracts.
    assert session.connector.tools[0].description == new_desc
    assert session.build_id != old_build_id


def test_delete_tool_refreshes_built_connector(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_build_connector")(name="Orders", slug="orders")
    _tool(mcp, "elliot_delete_tool")("list_orders")
    assert session.connector is not None
    assert session.connector.tools == []


# ── lint & quality scan operate on current state, not a stale snapshot ───────


def test_lint_scans_current_state_not_stale_build(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_build_connector")(name="Orders", slug="orders")
    # A second tool with a lint ERROR, created AFTER the build. The old code
    # linted the stale 1-tool snapshot and reported 0 issues.
    _tool(mcp, "elliot_create_tool")(
        name="dump_everything",
        description="Return every row of the orders table without limits.",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    out = _tool(mcp, "elliot_lint_connector")()
    assert out["scanned_tools"] == 2
    assert out["error_count"] >= 1
    codes = {i["code"] for i in out["issues"]}
    assert "UNBOUNDED_SELECT" in codes


def test_lint_enforces_product_intent_sensitive_fields(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_record_product_intent")(sensitive_fields=["amount"])
    out = _tool(mcp, "elliot_lint_connector")()
    codes = {i["code"] for i in out["issues"]}
    # Previously the MCP path never passed sensitive_fields, so this rule
    # could not fire despite the onboarding skill promising it.
    assert "SENSITIVE_FIELD_EXPOSED" in codes


def test_lint_without_build_works(mcp: FastMCP, session: ElliotSession, tmp_path: Path) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    out = _tool(mcp, "elliot_lint_connector")()
    assert "issues" in out
    assert out["scanned_tools"] == 1


def test_quality_scan_covers_all_tools_and_zeroes_broken_ones(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_build_connector")(name="Orders", slug="orders")
    # Simulate a tool whose source broke AFTER creation (the live-tenant case:
    # a feed source is registered but its table never materialized, while the
    # tool bound to it stayed in the registry).
    from elliot_core.types.source import SourceConfig

    session.sources["feed-uuid"] = SourceConfig.model_validate(
        {
            "id": "feed-uuid",
            "type": "rest",
            "name": "broken_feed",
            "url": "https://feed.example.com/items",
        }
    )
    session.registry.add(
        ToolDefinition.model_validate(
            {
                "id": "list_breaking_news",
                "name": "list_breaking_news",
                "description": "List the latest breaking news items from the feed.",
                "category": "READ",
                "source_ids": ["feed-uuid"],
            }
        )
    )
    session.tool_sql["list_breaking_news"] = 'SELECT headline FROM "broken_feed" LIMIT 5'

    out = _tool(mcp, "elliot_quality_scan")()
    scored = {ts["tool_id"]: ts for ts in out["tool_scores"]}
    # Every registry tool is scored — not just whatever the last build held.
    assert set(scored) == {"list_orders", "list_breaking_news"}
    broken = scored["list_breaking_news"]
    assert broken["score"] == 0.0
    assert any(i["check"] == "source_materialized" for i in broken["issues"])
    assert out["error_count"] >= 1
    assert out["overall_score"] < 100.0


# ── F3: same-name skill updates instead of minting duplicates ────────────────


def test_create_skill_same_name_updates_in_place(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    first = _tool(mcp, "elliot_create_skill")(
        name="order_brief",
        description="Produce a one-shot order brief.",
        steps=[{"alias": "orders", "tool_id": "list_orders", "params": {}}],
    )
    assert first == {"skill_id": "order_brief", "status": "created"}
    second = _tool(mcp, "elliot_create_skill")(
        name="order_brief",
        description="Produce a one-shot order brief, newest orders first.",
        steps=[{"alias": "orders", "tool_id": "list_orders", "params": {}}],
    )
    assert second == {"skill_id": "order_brief", "status": "updated"}
    skills = session.registry.get_all_skills()
    assert [s.id for s in skills] == ["order_brief"]
    assert "newest orders first" in skills[0].description


# ── token diet: list tools/sources are summaries by default ──────────────────


def test_list_tools_summary_by_default(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    out = _tool(mcp, "elliot_list_tools")()
    assert out["count"] == 1
    item = out["tools"][0]
    assert "sql" not in item
    assert item["parameters"] == []
    assert item["has_sql"] is True
    assert "note" in out

    full = _tool(mcp, "elliot_list_tools")(verbose=True)
    assert full["tools"][0]["sql"] == 'SELECT id, amount FROM "orders" LIMIT 10'


def test_list_sources_summary_by_default(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    out = _tool(mcp, "elliot_list_sources")()
    cols = out["sources"][0]["columns"]
    assert cols and all(isinstance(c, str) for c in cols)

    full = _tool(mcp, "elliot_list_sources")(verbose=True)
    vcols = full["sources"][0]["columns"]
    assert vcols and all(isinstance(c, dict) and "type" in c for c in vcols)


# ── audit batch: update_skill, list_skills diet, getting_started ─────────────


def test_update_skill_patches_in_place(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_create_skill")(
        name="order_brief",
        description="Produce a one-shot order brief.",
        steps=[{"alias": "o", "tool_id": "list_orders", "params": {}}],
    )
    out = _tool(mcp, "elliot_update_skill")(
        skill_id="order_brief", patch={"description": "Produce a two-step order brief with totals."}
    )
    assert out == {"skill_id": "order_brief", "status": "updated"}
    skill = session.registry.get_skill("order_brief")
    assert skill is not None and "two-step" in skill.description
    # Steps untouched by a description-only patch.
    assert [s.tool_id for s in skill.steps] == ["list_orders"]


def test_update_skill_unknown_id_and_unknown_step_tool(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    missing = _tool(mcp, "elliot_update_skill")(skill_id="ghost", patch={"description": "x"})
    assert "error" in missing
    _tool(mcp, "elliot_create_skill")(
        name="order_brief",
        description="Produce a one-shot order brief.",
        steps=[{"alias": "o", "tool_id": "list_orders", "params": {}}],
    )
    bad = _tool(mcp, "elliot_update_skill")(
        skill_id="order_brief",
        patch={"steps": [{"alias": "o", "tool_id": "nonexistent_tool", "params": {}}]},
    )
    assert "TOOL_NOT_FOUND" in str(bad)


def test_list_skills_summary_by_default(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
) -> None:
    _setup_source_and_tool(mcp, tmp_path)
    _tool(mcp, "elliot_create_skill")(
        name="order_brief",
        description="Produce a one-shot order brief.",
        steps=[{"alias": "o", "tool_id": "list_orders", "params": {}}],
    )
    out = _tool(mcp, "elliot_list_skills")()
    item = out["skills"][0]
    assert "steps" not in item
    assert item["step_count"] == 1
    full = _tool(mcp, "elliot_list_skills")(verbose=True)
    assert full["skills"][0]["steps"][0]["tool_id"] == "list_orders"


def test_getting_started_tool_returns_guide(mcp: FastMCP) -> None:
    out = _tool(mcp, "elliot_getting_started")()
    # In a source checkout the skills dir is found; the guide must be real text.
    assert "guide" in out, out
    assert len(out["guide"]) > 200
