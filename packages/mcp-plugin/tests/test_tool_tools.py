"""Tests for tool MCP tools: create, get, update, list, delete, preview."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_tool_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):
    fn = mcp._tool_manager._tools[name].fn
    if inspect.iscoroutinefunction(fn):
        try:
            asyncio.get_running_loop()
            return fn
        except RuntimeError:

            def sync_wrapper(*args, **kwargs):
                return asyncio.run(fn(*args, **kwargs))

            return sync_wrapper
    return fn


def _load_table(session: ElliotSession, tmp_path: Path) -> None:
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "orders.csv"
    p.write_text("id,amount\n1,100\n2,200\n3,300\n")
    _tool(s, "elliot_discover_source")(source_type="file", config={"path": str(p)}, name="orders")


def test_create_rest_tool_sets_passthrough(mcp: FastMCP, session: ElliotSession):
    from elliot_core.types.source import SourceConfig

    session.sources["api1"] = SourceConfig.model_validate(
        {"id": "api1", "type": "rest", "name": "api1", "url": "https://api.example.com/search"}
    )
    out = _tool(mcp, "elliot_create_rest_tool")(
        name="Search records",
        description="Search a resource's records live via the API.",
        source_id="api1",
        query_params=[
            {
                "name": "resource_id",
                "type": "string",
                "required": True,
                "description": "resource id",
            },
            {"name": "q", "type": "string", "required": False, "description": "text filter"},
        ],
    )
    assert out.get("status") == "created", out
    tool = session.registry.get(out["tool_id"])
    assert tool is not None
    assert tool.rest_query_params == ["resource_id", "q"]
    assert tool.source_ids == ["api1"]
    assert {p.name for p in tool.parameters} == {"resource_id", "q"}


def test_create_rest_tool_rejects_non_rest_source(mcp: FastMCP, session: ElliotSession):
    from elliot_core.types.source import SourceConfig

    session.sources["f1"] = SourceConfig.model_validate(
        {"id": "f1", "type": "file", "name": "f1", "path": "/tmp/x.json"}
    )
    out = _tool(mcp, "elliot_create_rest_tool")(
        name="X tool",
        description="should be rejected",
        source_id="f1",
        query_params=[{"name": "a"}],
    )
    assert "error" in out


# ---------------------------------------------------------------------------
# elliot_create_tool
# ---------------------------------------------------------------------------


def test_create_tool_returns_tool_id(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="total_orders",
        description="Returns total order count",
        category="READ",
        sql='SELECT COUNT(*) as cnt FROM "orders"',
        parameters=[],
    )
    assert result["status"] == "created"
    assert result["tool_id"] == "total_orders"


def test_create_tool_slugifies_free_text_name(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    # A natural name with spaces must become a snake_case id, not a raw id with
    # spaces (which blew up downstream as [Errno 22] on Windows).
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="List Orders",
        description="Return all orders in the system",
        category="read",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    assert result["tool_id"] == "list_orders"


def test_create_tool_rejects_unsluggable_name(mcp: FastMCP, session: ElliotSession):
    result = _tool(mcp, "elliot_create_tool")(
        name="!!!",
        description="Return all orders in the system",
        category="read",
        sql="SELECT 1",
        parameters=[],
    )
    # No letters survive slugification -> actionable validation error, not a crash.
    blob = result.get("text", "") + result.get("error", "")
    assert "INVALID_TOOL_NAME" in blob or "valid tool id" in blob


def test_create_tool_stores_in_registry(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="sum_orders",
        description="Sum of all order amounts",
        category="READ",
        sql='SELECT SUM(amount) as total FROM "orders"',
        parameters=[],
    )
    assert session.registry.get("sum_orders") is not None
    assert session.tool_sql["sum_orders"] == 'SELECT SUM(amount) as total FROM "orders"'


def test_create_tool_aggregate_category_mapped(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="count_orders",
        description="Count all orders in the system",
        category="AGGREGATE",
        sql='SELECT COUNT(*) as cnt FROM "orders"',
        parameters=[],
    )
    assert result["status"] == "created"
    tool = session.registry.get("count_orders")
    assert tool is not None
    assert tool.category == "READ"


# ---------------------------------------------------------------------------
# elliot_get_tool
# ---------------------------------------------------------------------------


def test_get_tool_returns_definition_and_sql(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="get_orders",
        description="Retrieve all orders from system",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_get_tool")(tool_id="get_orders")
    assert result["id"] == "get_orders"
    assert result["sql"] == 'SELECT * FROM "orders"'


def test_get_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_tool")(tool_id="ghost")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# elliot_list_tools
# ---------------------------------------------------------------------------


def test_list_tools_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_list_tools")()
    assert result["count"] == 0


def test_list_tools_after_create(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="list_orders",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_list_tools")()
    assert result["count"] == 1
    assert result["tools"][0]["id"] == "list_orders"
    # SQL is stored in session.tool_sql, not on the model — the list endpoint
    # must merge it in so the Studio editor can render the query.
    assert result["tools"][0]["sql"] == 'SELECT * FROM "orders"'


# ---------------------------------------------------------------------------
# elliot_delete_tool
# ---------------------------------------------------------------------------


def test_delete_tool_removes_from_registry(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="del_orders",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_delete_tool")(tool_id="del_orders")
    assert result["status"] == "deleted"
    assert session.registry.get("del_orders") is None
    assert "del_orders" not in session.tool_sql


def test_delete_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_delete_tool")(tool_id="nonexistent")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# elliot_update_tool
# ---------------------------------------------------------------------------


def test_update_tool_sql(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="upd_orders",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    _tool(mcp, "elliot_update_tool")(
        tool_id="upd_orders",
        patch={"sql": 'SELECT COUNT(*) as cnt FROM "orders"'},
    )
    assert session.tool_sql["upd_orders"] == 'SELECT COUNT(*) as cnt FROM "orders"'


def test_update_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_update_tool")(tool_id="ghost", patch={"sql": "SELECT 1"})
    assert "text" in result or "error" in result


def test_update_tool_reinfers_source_ids_when_sql_changes(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Regression: changing a tool's SQL to reference a different source must
    re-infer source_ids. Otherwise the tool keeps the old source_ids, the
    runtime materializes the wrong tables, and the SQL hits "no such table" /
    returns 0 rows at call time while lint stays green (the data.gov.il bug)."""
    _load_table(session, tmp_path)  # source "orders"

    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p2 = tmp_path / "customers.csv"
    p2.write_text("id,name\n1,Ann\n2,Bob\n")
    _tool(s, "elliot_discover_source")(
        source_type="file", config={"path": str(p2)}, name="customers"
    )

    orders_sid = next(sid for sid, src in session.sources.items() if src.name == "orders")
    customers_sid = next(sid for sid, src in session.sources.items() if src.name == "customers")

    _tool(mcp, "elliot_create_tool")(
        name="repointed",
        description="Retrieve all orders from the database",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    assert session.registry.get("repointed").source_ids == [orders_sid]

    _tool(mcp, "elliot_update_tool")(
        tool_id="repointed",
        patch={"sql": 'SELECT * FROM "customers"'},
    )

    # source_ids must now follow the SQL to the customers source.
    assert session.registry.get("repointed").source_ids == [customers_sid]


# ---------------------------------------------------------------------------
# elliot_preview_tool
# ---------------------------------------------------------------------------


def test_preview_tool_returns_rows(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="preview_orders",
        description="Retrieve all orders from the system",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="preview_orders", params={})
    assert result["row_count"] == 3


def test_preview_tool_aggregate(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="total_amount",
        description="Returns the total sum of all orders",
        category="AGGREGATE",
        sql='SELECT SUM(amount) as total FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="total_amount", params={})
    assert result["row_count"] == 1


def test_preview_tool_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_preview_tool")(tool_id="ghost", params={})
    assert "text" in result or "error" in result


# ── Bug #2 regression: accept arguments/parameters aliases ───────────────────


def test_preview_tool_accepts_arguments_alias(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="orders_by_amount",
        description="Return orders with amount above threshold",
        category="READ",
        sql='SELECT * FROM "orders" WHERE amount > :threshold',
        parameters=[
            {"name": "threshold", "type": "integer", "required": True, "description": "min"}
        ],
    )
    result = _tool(mcp, "elliot_preview_tool")(
        tool_id="orders_by_amount", arguments={"threshold": 1}
    )
    assert "row_count" in result


def test_preview_tool_accepts_parameters_alias(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="orders_all",
        description="Return all orders",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="orders_all", parameters={})
    assert result["row_count"] == 3


# ── Bug #3 regression: structured VALIDATION_REQUIRED for missing required ───


def test_preview_tool_missing_required_returns_structured_error(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    _tool(mcp, "elliot_create_tool")(
        name="orders_by_status",
        description="Return orders for the given status",
        category="READ",
        sql='SELECT * FROM "orders" WHERE status = :status',
        parameters=[
            {"name": "status", "type": "string", "required": True, "description": "status"}
        ],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id="orders_by_status", params={})
    # to_mcp_error_content returns {"type": "text", "text": "[CODE] msg"}
    assert "VALIDATION_REQUIRED" in result.get("text", "")
    assert "status" in result.get("text", "")


# ── elliot_validate_tool accepts the same shape as elliot_create_tool ────────


def test_validate_tool_accepts_create_tool_shape(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Regression: elliot_validate_tool used to reject inputs that
    elliot_create_tool would happily accept (missing `id`, lowercase
    `category`)."""
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_validate_tool")(
        tool={
            "name": "orders_by_status",
            "description": "Return orders for the given status filter",
            "category": "read",
            "source_ids": list(session.sources.keys()),
            "parameters": [
                {"name": "status", "type": "string", "required": False, "description": "status"}
            ],
        }
    )
    assert result == {"valid": True}


def test_validate_tool_still_rejects_genuinely_invalid_input(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_validate_tool")(
        tool={
            "name": "x",  # too generic and description too short
            "description": "short",
            "category": "read",
            "source_ids": list(session.sources.keys()),
            "parameters": [],
        }
    )
    assert result["valid"] is False
    assert "error" in result


def test_create_tool_rejects_non_select_sql(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    """A tool whose SQL is not a read-only SELECT must be refused at creation,
    not stored and executed against the in-memory mirror at call time."""
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="evil",
        description="Drops a table",
        category="READ",
        sql='DROP TABLE "orders"',
        parameters=[],
    )
    assert "INVALID_SQL" in result.get("text", "")
    assert "evil" not in session.registry._tools if hasattr(session.registry, "_tools") else True


# ── B2: create_tool registration guards ─────────────────────────────────────


def test_create_tool_rejects_undeclared_param(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    """An undeclared :param used to register fine and fail only at call time."""
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="orders_capped",
        description="Return orders up to a cap",
        category="READ",
        sql='SELECT id, amount FROM "orders" LIMIT :max_fast',
        parameters=[],  # :max_fast is NOT declared
    )
    assert "UNDECLARED_PARAM" in result.get("text", "")
    assert "max_fast" in result.get("text", "")
    assert session.registry.get("orders_capped") is None


def test_create_tool_warns_on_select_star(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    """SELECT * is allowed but flagged as a non-blocking authoring smell."""
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="orders_all_cols",
        description="Return every order column",
        category="READ",
        sql='SELECT * FROM "orders"',
        parameters=[],
    )
    assert result.get("status") == "created", result
    assert any("SELECT *" in w for w in result.get("warnings", []))


# ── M1: validate_tool infers source_ids like create_tool ────────────────────


def test_validate_tool_infers_source_ids_from_sql(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """A READ tool with SQL but no explicit source_ids validates (create infers it)."""
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_validate_tool")(
        tool={
            "name": "orders_listing",
            "description": "Return all orders for the agent",
            "category": "read",
            "sql": 'SELECT id, amount FROM "orders"',
            "parameters": [],
        }
    )
    assert result == {"valid": True}


# ── H8: REST passthrough tools are previewable live ─────────────────────────


def test_preview_passthrough_tool_fetches_live(
    mcp: FastMCP, session: ElliotSession, monkeypatch: pytest.MonkeyPatch
):
    from elliot_core.types.source import FetchResult, SourceConfig

    session.sources["api1"] = SourceConfig.model_validate(
        {"id": "api1", "type": "rest", "name": "api1", "url": "https://api.example.com/search"}
    )
    created = _tool(mcp, "elliot_create_rest_tool")(
        name="Search records",
        description="Search a resource's records live via the API.",
        source_id="api1",
        query_params=[
            {"name": "q", "type": "string", "required": True, "description": "text filter"},
        ],
    )
    tool_id = created["tool_id"]

    captured: dict = {}

    async def _fake_fetch(config, secrets, *, auth_token_override=None, extra_params=None):
        captured["extra_params"] = extra_params
        return FetchResult(rows=[{"id": 1, "name": "widget"}], fetched_at="now")

    monkeypatch.setattr("elliot_core.sources.api_fetcher.fetch_endpoint", _fake_fetch)

    result = _tool(mcp, "elliot_preview_tool")(tool_id=tool_id, params={"q": "widget"})
    assert result.get("mode") == "rest_passthrough"
    assert result.get("live") is True
    assert result["rows"] == [{"id": 1, "name": "widget"}]
    assert captured["extra_params"] == {"q": "widget"}


def test_preview_passthrough_tool_enforces_required(mcp: FastMCP, session: ElliotSession):
    from elliot_core.types.source import SourceConfig

    session.sources["api1"] = SourceConfig.model_validate(
        {"id": "api1", "type": "rest", "name": "api1", "url": "https://api.example.com/search"}
    )
    created = _tool(mcp, "elliot_create_rest_tool")(
        name="Search records",
        description="Search a resource's records live via the API.",
        source_id="api1",
        query_params=[
            {"name": "q", "type": "string", "required": True, "description": "text filter"},
        ],
    )
    result = _tool(mcp, "elliot_preview_tool")(tool_id=created["tool_id"], params={})
    assert "VALIDATION_REQUIRED" in result.get("text", "")


def test_create_tool_rejects_undeclared_bind_param(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    # B2 regression: a :param with no matching declared parameter must be
    # rejected at create time, not accepted and then failing at call time.
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="expensive_orders",
        description="Return orders above a price threshold.",
        category="READ",
        sql='SELECT id FROM "orders" WHERE amount > :max_price',
        parameters=[],
    )
    assert "UNDECLARED_PARAM" in result.get("text", ""), result
    assert session.registry.get("expensive_orders") is None


def test_create_tool_accepts_declared_bind_param(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_create_tool")(
        name="expensive_orders",
        description="Return orders above a price threshold.",
        category="READ",
        sql='SELECT id FROM "orders" WHERE amount > :max_price',
        parameters=[
            {
                "name": "max_price",
                "type": "number",
                "required": True,
                "description": "Minimum order amount to include.",
            }
        ],
    )
    assert result.get("status") == "created", result


# ── elliot_create_action_tool ─────────────────────────────────────────────────


def _rest_source(session: ElliotSession, source_id: str = "shop") -> None:
    from elliot_core.types.source import SourceConfig

    session.sources[source_id] = SourceConfig.model_validate(
        {"id": source_id, "type": "rest", "name": source_id, "url": "https://api.example.com/shop"}
    )


def test_create_action_tool_registers_api_mapping(mcp: FastMCP, session: ElliotSession):
    _rest_source(session)
    out = _tool(mcp, "elliot_create_action_tool")(
        name="cancel_order",
        description="Cancel an order by id, notifying the customer.",
        source_id="shop",
        method="post",
        path_template="/orders/{order_id}/cancel",
        body_params=["reason"],
        parameters=[
            {
                "name": "order_id",
                "type": "string",
                "required": True,
                "description": "Order to cancel.",
            },
            {
                "name": "reason",
                "type": "string",
                "required": False,
                "description": "Optional cancellation reason shown to the customer.",
            },
        ],
    )
    assert out.get("status") == "created", out
    assert out.get("mode") == "api_mutation"
    tool = session.registry.get("cancel_order")
    assert tool is not None
    assert tool.category == "ACTION"
    assert tool.api_mapping is not None
    assert tool.api_mapping.method == "POST"
    assert tool.api_mapping.path_template == "/orders/{order_id}/cancel"
    assert tool.api_mapping.body_params == ["reason"]
    assert tool.source_ids == ["shop"]
    assert "cancel_order" not in session.tool_sql


def test_create_action_tool_rejects_unknown_and_non_rest_source(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    out = _tool(mcp, "elliot_create_action_tool")(
        name="x",
        description="d",
        source_id="ghost",
        method="POST",
        parameters=[{"name": "a", "type": "string", "required": True, "description": "a"}],
        body_params=["a"],
    )
    assert "Source not found" in out.get("error", "")

    _load_table(session, tmp_path)  # registers a file source named "orders"
    file_source_id = next(iter(session.sources))
    out = _tool(mcp, "elliot_create_action_tool")(
        name="x",
        description="d",
        source_id=file_source_id,
        method="POST",
        parameters=[{"name": "a", "type": "string", "required": True, "description": "a"}],
        body_params=["a"],
    )
    assert "not 'rest'" in out.get("error", "")


def test_create_action_tool_rejects_get_method(mcp: FastMCP, session: ElliotSession):
    _rest_source(session)
    out = _tool(mcp, "elliot_create_action_tool")(
        name="fetch_things",
        description="d",
        source_id="shop",
        method="GET",
        parameters=[{"name": "a", "type": "string", "required": True, "description": "a"}],
        query_params=["a"],
    )
    assert "POST, PUT, PATCH or DELETE" in out.get("error", "")


def test_create_action_tool_rejects_undeclared_placeholder(mcp: FastMCP, session: ElliotSession):
    _rest_source(session)
    out = _tool(mcp, "elliot_create_action_tool")(
        name="cancel_order",
        description="Cancel an order.",
        source_id="shop",
        method="POST",
        path_template="/orders/{order_id}/cancel",
        parameters=[{"name": "reason", "type": "string", "required": False, "description": "why"}],
        body_params=["reason"],
    )
    text = str(out)
    assert "UNDECLARED_PARAM" in text and "order_id" in text


def test_create_action_tool_rejects_unrouted_param(mcp: FastMCP, session: ElliotSession):
    _rest_source(session)
    out = _tool(mcp, "elliot_create_action_tool")(
        name="update_note",
        description="Update a note.",
        source_id="shop",
        method="PATCH",
        parameters=[
            {"name": "note_id", "type": "string", "required": True, "description": "id"},
            {"name": "text", "type": "string", "required": True, "description": "body"},
        ],
        body_params=["text"],
    )
    out_text = str(out)
    assert "UNROUTED_PARAM" in out_text and "note_id" in out_text


def test_preview_action_tool_says_why_not(mcp: FastMCP, session: ElliotSession):
    _rest_source(session)
    _tool(mcp, "elliot_create_action_tool")(
        name="cancel_order",
        description="Cancel an order by id.",
        source_id="shop",
        method="POST",
        path_template="/orders/{order_id}/cancel",
        parameters=[{"name": "order_id", "type": "string", "required": True, "description": "id"}],
    )
    out = _tool(mcp, "elliot_preview_tool")(tool_id="cancel_order", params={"order_id": "9"})
    assert "ACTION_PREVIEW_UNAVAILABLE" in str(out)


def test_authored_action_tool_executes_in_runtime():
    """The whole point: a tool authored via elliot_create_action_tool must be
    executable by the published runtime as a real HTTP mutation."""
    import asyncio as _asyncio
    import json as _json

    import respx
    from httpx import Response

    from elliot_connector_runtime.executor import ToolExecutor as RuntimeExecutor
    from elliot_core.types import ConnectorConfig

    spec = {
        "name": "Shop",
        "slug": "shop",
        "version": "1.0.0",
        "sources": [
            {"id": "shop", "name": "shop", "type": "rest", "url": "https://api.example.com/shop"}
        ],
        "tools": [
            {
                "id": "cancel_order",
                "name": "cancel_order",
                "description": "Cancel an order by id.",
                "category": "ACTION",
                "source_ids": ["shop"],
                "parameters": [
                    {
                        "name": "order_id",
                        "type": "string",
                        "required": True,
                        "description": "id",
                    },
                    {
                        "name": "reason",
                        "type": "string",
                        "required": False,
                        "description": "why",
                    },
                ],
                "api_mapping": {
                    "method": "POST",
                    "path_template": "/orders/{order_id}/cancel",
                    "query_params": [],
                    "body_params": ["reason"],
                    "body_format": "json",
                },
            }
        ],
        "skills": [],
    }
    config = ConnectorConfig.model_validate(spec)
    executor = RuntimeExecutor(config, {})

    with respx.mock:
        route = respx.post("https://api.example.com/shop/orders/o-42/cancel").mock(
            return_value=Response(200, json={"ok": True, "order_id": "o-42"})
        )
        result = _asyncio.run(
            executor.execute(config.tools[0], {"order_id": "o-42", "reason": "customer ask"})
        )
    assert route.called
    sent_body = _json.loads(route.calls[0].request.content)
    assert sent_body == {"reason": "customer ask"}
    assert result.rows and result.rows[0]["ok"] is True
