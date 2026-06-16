"""Tests for source MCP tools: discover, list, preview, profile, refresh, remove."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.source_tools import _build_source_config, register_source_tools


def test_auth_bearer_token_alias_normalized() -> None:
    sc = _build_source_config(
        "rest", {"url": "https://api.x.com", "auth": {"type": "bearer", "token": "abc"}}, "s", "n"
    )
    assert sc.auth is not None and sc.auth.secret_key == "abc"


def test_auth_basic_username_password_alias_normalized() -> None:
    sc = _build_source_config(
        "rest",
        {"url": "https://api.x.com", "auth": {"type": "basic", "username": "u", "password": "p"}},
        "s",
        "n",
    )
    assert sc.auth is not None and sc.auth.secret_key == "u:p"


def test_auth_alias_and_secret_key_conflict_raises() -> None:
    with pytest.raises(ElliotError) as ei:
        _build_source_config(
            "rest",
            {
                "url": "https://api.x.com",
                "auth": {"type": "bearer", "token": "a", "secret_key": "b"},
            },
            "s",
            "n",
        )
    assert ei.value.code == "VALIDATION_ERROR"


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_source_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):
    fn = mcp._tool_manager._tools[name].fn
    if inspect.iscoroutinefunction(fn):
        try:
            asyncio.get_running_loop()
            return fn  # inside async test — caller will await directly
        except RuntimeError:

            def sync_wrapper(*args, **kwargs):
                return asyncio.run(fn(*args, **kwargs))

            return sync_wrapper
    return fn


def test_delete_source_prunes_source_and_dependent_tools(mcp, session):
    delete = _tool(mcp, "elliot_delete_source")
    src = SourceConfig.model_validate(
        {"id": "s1", "type": "file", "name": "people", "path": "/tmp/people.json"}
    )
    src.table_name = "people"
    session.sources["s1"] = src
    tool = ToolDefinition.model_validate(
        {
            "id": "list_people",
            "name": "List people",
            "description": "Lists people from the source.",
            "category": "READ",
            "source_ids": ["s1"],
            "parameters": [],
        }
    )
    session.registry.add(tool)
    session.tool_sql["list_people"] = "SELECT * FROM people"
    session.save()

    result = delete("s1")
    assert result.get("status") == "removed", result
    assert "s1" not in session.sources
    # Cascade: the tool bound to the deleted source is gone too.
    assert session.registry.get("list_people") is None


def test_delete_source_unknown_returns_error(mcp, session):
    delete = _tool(mcp, "elliot_delete_source")
    assert "error" in delete("does-not-exist")


def _is_error(result: dict) -> bool:  # type: ignore[type-arg]
    """Accept both {"error": ...} and to_mcp_error_content {"type":"text","text":"..."} formats."""
    return "error" in result or result.get("type") == "text"


def _csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "items.csv"
    p.write_text("id,name,price\n1,Apple,1.5\n2,Banana,0.75\n3,Cherry,2.0\n")
    return p


# ---------------------------------------------------------------------------
# elliot_discover_source — file
# ---------------------------------------------------------------------------


def test_discover_source_csv_returns_expected_keys(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path), "format": "csv"},
        name="items",
    )
    assert "source_id" in result
    assert result["table_name"] == "items"
    assert result["row_count"] == 3
    assert "columns" in result
    assert "warnings" in result


def test_discover_source_csv_columns_match(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path), "format": "csv"},
        name="items",
    )
    assert set(result["columns"]) >= {"id", "name", "price"}


def _nested_json_file(tmp_path: Path) -> Path:
    """A deeply nested record: project → invoices[] → line_items[], plus a
    nested owner object — the shape a real REST API returns."""
    p = tmp_path / "projects.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "p1",
                    "name": "Checkout",
                    "owner": {"id": "u1", "name": "Ada"},
                    "invoices": [
                        {
                            "id": "inv1",
                            "total": 100,
                            "line_items": [{"amount": 60}, {"amount": 40}],
                        },
                        {"id": "inv2", "total": 50, "line_items": [{"amount": 50}]},
                    ],
                }
            ]
        )
    )
    return p


def test_discover_surfaces_nested_child_tables(mcp: FastMCP, tmp_path: Path):
    """Regression: a nested response must expose EVERY flattened table (not just
    the primary one) so an agent can JOIN/aggregate across the nesting. Before
    this, the child tables where the nested data lives were invisible."""
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(_nested_json_file(tmp_path)), "format": "json"},
        name="projects",
    )
    names = {t["name"]: t for t in result["tables"]}
    # Primary + both levels of child tables are surfaced.
    assert names["projects"]["role"] == "primary"
    assert "projects_invoices" in names
    assert "projects_invoices_line_items" in names
    # Parent linkage is correct even two levels deep.
    assert names["projects_invoices"]["parent"] == "projects"
    assert names["projects_invoices_line_items"]["parent"] == "projects_invoices"
    # The aggregation column the agent needs is listed, with the join key.
    inv_cols = names["projects_invoices"]["columns"]
    assert "total" in inv_cols and "_parent_id" in inv_cols
    # And the agent is told HOW to join.
    assert result["schema_hint"] and "_parent_id" in result["schema_hint"]


def test_list_sources_includes_child_tables_after_rediscover(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """The full relational schema must survive a re-list (e.g. the agent builds
    tools in a later call) — child tables come back from persisted state."""
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(_nested_json_file(tmp_path)), "format": "json"},
        name="projects",
    )
    listed = _tool(mcp, "elliot_list_sources")()
    src = listed["sources"][0]
    related = {t["name"] for t in src["related_tables"]}
    assert {"projects_invoices", "projects_invoices_line_items"} <= related
    assert src["schema_hint"]


def test_discover_source_registers_in_session(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="things",
    )
    sid = result["source_id"]
    assert sid in session.sources
    assert session.sources[sid].table_name == "things"


def test_discover_source_json_file(mcp: FastMCP, tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"a": 1}, {"a": 2}]))
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(p), "format": "json"},
        name="data",
    )
    assert result["row_count"] == 2


def test_discover_source_unknown_type_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_discover_source")(
        source_type="ftp",
        config={},
        name="x",
    )
    assert "text" in result or "error" in result
    assert "ftp" in result["error"]


# ── source_type alias acceptance (regression: Bug #1) ─────────────────────────


def test_discover_source_accepts_rest_alias(mcp: FastMCP, session: ElliotSession):
    """The Studio UI sends source_type='rest' (matching SourceConfig.type),
    not the agent-friendly 'api'. Both must be accepted."""
    from elliot_core.types.source import FetchResult

    async def fake_fetch(cfg, secrets):
        return FetchResult(rows=[{"id": 1, "n": "x"}], fetched_at="t")

    import elliot_mcp_plugin.tools.source_tools as st

    original = st.fetch_endpoint
    st.fetch_endpoint = fake_fetch  # type: ignore[assignment]
    try:
        result = _tool(mcp, "elliot_discover_source")(
            source_type="rest",
            config={"url": "https://api.example.com/items"},
            name="items",
        )
    finally:
        st.fetch_endpoint = original  # type: ignore[assignment]
    assert "error" not in result, result
    assert result["row_count"] == 1


def test_discover_source_accepts_postgres_alias(mcp: FastMCP):
    """Studio sends source_type='postgres' (UI label). Must map to db path."""
    import elliot_mcp_plugin.tools.source_tools as st
    from elliot_core.types.source import FetchResult

    original = st.query_database
    st.query_database = lambda cfg, secrets: FetchResult(  # type: ignore[assignment]
        rows=[{"id": 1}], fetched_at="t"
    )
    try:
        result = _tool(mcp, "elliot_discover_source")(
            source_type="postgres",
            config={"url": "postgresql://u:p@h/d", "table": "t"},
            name="t",
        )
    finally:
        st.query_database = original  # type: ignore[assignment]
    assert "error" not in result, result
    assert result["table_name"] == "t"


def test_discover_source_missing_file_returns_error(mcp: FastMCP, tmp_path: Path):
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(tmp_path / "missing.csv")},
        name="x",
    )
    assert _is_error(result)


def test_discover_source_api_success(mcp: FastMCP, session: ElliotSession):
    from elliot_core.types.source import FetchResult

    fake_result = FetchResult(
        rows=[{"id": 1, "val": "a"}, {"id": 2, "val": "b"}],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    with patch(
        "elliot_mcp_plugin.tools.source_tools.fetch_endpoint",
        new=AsyncMock(return_value=fake_result),
    ):
        result = _tool(mcp, "elliot_discover_source")(
            source_type="api",
            config={"url": "https://api.example.com/items"},
            name="api_items",
        )
    assert result["row_count"] == 2
    assert result["table_name"] == "api_items"


def test_discover_source_db_success(mcp: FastMCP):
    from elliot_core.types.source import FetchResult

    fake_result = FetchResult(
        rows=[{"col": "val"}],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    with patch("elliot_mcp_plugin.tools.source_tools.query_database", return_value=fake_result):
        result = _tool(mcp, "elliot_discover_source")(
            source_type="db",
            config={"table": "users"},
            name="users",
        )
    assert result["row_count"] == 1


# ---------------------------------------------------------------------------
# elliot_list_sources
# ---------------------------------------------------------------------------


def test_list_sources_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_list_sources")()
    assert result["count"] == 0
    assert result["sources"] == []


def test_list_sources_after_discover(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="tbl",
    )
    result = _tool(mcp, "elliot_list_sources")()
    assert result["count"] == 1
    assert result["sources"][0]["name"] == "tbl"


def test_list_sources_count_multiple(mcp: FastMCP, tmp_path: Path):
    for i in range(3):
        p = tmp_path / f"f{i}.json"
        p.write_text(json.dumps([{"x": i}]))
        _tool(mcp, "elliot_discover_source")(
            source_type="file",
            config={"path": str(p)},
            name=f"t{i}",
        )
    result = _tool(mcp, "elliot_list_sources")()
    assert result["count"] == 3


# ---------------------------------------------------------------------------
# elliot_preview_source
# ---------------------------------------------------------------------------


def test_preview_source_returns_rows_and_schema(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    result = _tool(mcp, "elliot_preview_source")(table_name="items")
    assert result["row_count"] == 3
    assert len(result["rows"]) == 3
    assert isinstance(result["schema"], list)


def test_preview_source_limit_respected(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    result = _tool(mcp, "elliot_preview_source")(table_name="items", limit=2)
    assert result["row_count"] == 2


def test_preview_source_missing_table_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_preview_source")(table_name="nonexistent")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# elliot_profile_source
# ---------------------------------------------------------------------------


def test_profile_source_returns_column_stats(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    result = _tool(mcp, "elliot_profile_source")(table_name="items")
    assert result["table"] == "items"
    assert result["row_count"] == 3
    assert "columns" in result


def test_profile_source_missing_table_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_profile_source")(table_name="ghost")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# studio_remove_source
# ---------------------------------------------------------------------------


def test_remove_source_removes_from_session(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    sid = disc["source_id"]
    result = _tool(mcp, "studio_remove_source")(source_id=sid)
    assert result["status"] == "removed"
    assert sid not in session.sources


def test_remove_source_drops_table(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    sid = disc["source_id"]
    _tool(mcp, "studio_remove_source")(source_id=sid)
    # Table should no longer appear in list_sources
    lst = _tool(mcp, "elliot_list_sources")()
    assert lst["count"] == 0


def test_remove_source_table_no_longer_previewable(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    _tool(mcp, "studio_remove_source")(source_id=disc["source_id"])
    result = _tool(mcp, "elliot_preview_source")(table_name="items")
    assert "text" in result or "error" in result


def test_remove_source_not_found_returns_error(mcp: FastMCP):
    result = _tool(mcp, "studio_remove_source")(source_id="no-such-id")
    assert "text" in result or "error" in result


def test_remove_source_cascades_to_dependent_tools(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    register_tool_tools(mcp, session)
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    sid = disc["source_id"]
    _tool(mcp, "elliot_create_tool")(
        name="count_items",
        description="Count items in the catalog",
        category="READ",
        sql='SELECT COUNT(*) AS cnt FROM "items"',
        parameters=[],
    )
    assert session.registry.get("count_items") is not None
    assert "count_items" in session.tool_sql

    result = _tool(mcp, "studio_remove_source")(source_id=sid)
    assert result["status"] == "removed"
    assert result["removed_tool_ids"] == ["count_items"]
    assert session.registry.get("count_items") is None
    assert "count_items" not in session.tool_sql


def test_remove_source_leaves_unrelated_tools(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    register_tool_tools(mcp, session)
    items_csv = _csv_file(tmp_path)
    other_csv = tmp_path / "orders.csv"
    other_csv.write_text("id,amount\n1,100\n2,200\n")
    items_disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(items_csv)},
        name="items",
    )
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(other_csv)},
        name="orders",
    )
    _tool(mcp, "elliot_create_tool")(
        name="count_orders",
        description="Count orders placed by customers",
        category="READ",
        sql='SELECT COUNT(*) AS cnt FROM "orders"',
        parameters=[],
    )

    result = _tool(mcp, "studio_remove_source")(source_id=items_disc["source_id"])
    assert result["status"] == "removed"
    assert result["removed_tool_ids"] == []
    assert session.registry.get("count_orders") is not None


# ---------------------------------------------------------------------------
# elliot_refresh_source
# ---------------------------------------------------------------------------


def test_refresh_source_reloads_data(mcp: FastMCP, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    sid = disc["source_id"]
    result = _tool(mcp, "elliot_refresh_source")(source_id=sid)
    assert result["row_count"] == 3


def test_refresh_source_not_found_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_refresh_source")(source_id="bad-id")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# Error containment — no raw exception escapes
# ---------------------------------------------------------------------------


def test_discover_exception_does_not_raise(mcp: FastMCP):
    with patch("elliot_mcp_plugin.tools.source_tools.read_file", side_effect=RuntimeError("boom")):
        result = _tool(mcp, "elliot_discover_source")(
            source_type="file",
            config={"path": "/some/path.csv"},
            name="x",
        )
    assert "text" in result or "error" in result


def test_list_sources_exception_does_not_raise(mcp: FastMCP, session: ElliotSession):
    session.sources = None  # type: ignore[assignment]
    result = _tool(mcp, "elliot_list_sources")()
    assert "text" in result or "error" in result


# ── elliot_upload_file ──────────────────────────────────────────────────────


def test_upload_file_round_trips_through_discover_source(
    mcp: FastMCP, session: ElliotSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The whole point of the tool: upload then discover, without any
    ELLIOT_FILE_ROOT tuning, regardless of cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ELLIOT_FILE_ROOT", raising=False)
    monkeypatch.delenv("ELLIOT_FILE_READER_ALLOW_ABSOLUTE", raising=False)

    payload = json.dumps([{"id": 1, "name": "Ada"}, {"id": 2, "name": "Lin"}])
    upload = _tool(mcp, "elliot_upload_file")(file_name="people.json", content=payload)
    assert "managed_path" in upload
    assert upload["file_name"] == "people.json"
    assert upload["size_bytes"] == len(payload.encode("utf-8"))
    # File actually exists where we said it did.
    assert Path(upload["managed_path"]).read_text() == payload

    # And discover_source can read it back without tuning ELLIOT_FILE_ROOT.
    out = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": upload["managed_path"]},
        name="people",
    )
    assert "source_id" in out
    assert out["row_count"] == 2


def test_upload_file_rejects_path_separators(mcp: FastMCP):
    bad = _tool(mcp, "elliot_upload_file")(file_name="../escape.json", content="{}")
    assert "text" in bad
    assert "INVALID_FILE_NAME" in bad["text"]


def test_upload_file_rejects_absolute(mcp: FastMCP):
    bad = _tool(mcp, "elliot_upload_file")(file_name="/etc/passwd", content="{}")
    assert "text" in bad
    assert "INVALID_FILE_NAME" in bad["text"]


def test_upload_file_rejects_disallowed_extension(mcp: FastMCP):
    bad = _tool(mcp, "elliot_upload_file")(file_name="evil.sh", content="echo")
    assert "text" in bad
    assert "INVALID_FILE_NAME" in bad["text"]


def test_upload_file_rejects_oversize(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_UPLOAD_MAX_BYTES", "1024")
    big = "x" * 4096
    bad = _tool(mcp, "elliot_upload_file")(file_name="big.csv", content=big)
    assert "text" in bad
    assert "FILE_TOO_LARGE" in bad["text"]


def test_upload_file_base64_encoding(mcp: FastMCP):
    import base64 as _b64

    raw = b'[{"id":1}]'
    encoded = _b64.b64encode(raw).decode("ascii")
    out = _tool(mcp, "elliot_upload_file")(file_name="bin.json", content=encoded, encoding="base64")
    assert "managed_path" in out
    assert Path(out["managed_path"]).read_bytes() == raw


def test_upload_file_invalid_base64(mcp: FastMCP):
    bad = _tool(mcp, "elliot_upload_file")(
        file_name="bin.json", content="not::base64", encoding="base64"
    )
    assert "text" in bad
    assert "VALIDATION_ERROR" in bad["text"]


def test_upload_file_overwrite_is_atomic(mcp: FastMCP, session: ElliotSession):
    """A second upload to the same filename replaces atomically, no .tmp left."""
    _tool(mcp, "elliot_upload_file")(file_name="x.json", content='{"v":1}')
    out = _tool(mcp, "elliot_upload_file")(file_name="x.json", content='{"v":2}')
    assert Path(out["managed_path"]).read_text() == '{"v":2}'
    leftover = Path(out["managed_path"]).with_name("x.json.tmp")
    assert not leftover.exists()


# ── file sources are self-contained (inline content survives publish/restart) ─


def test_discover_file_with_inline_content_no_disk(mcp: FastMCP, session: ElliotSession):
    """An agent can register a file source in ONE call by passing the body
    inline — no upload, no path, no ELLIOT_FILE_ROOT, no disk access at all."""
    out = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"content": '[{"id": 1}, {"id": 2}]', "format": "json"},
        name="people",
    )
    assert out["row_count"] == 2
    # The bytes are persisted ON the source, so it travels into the published
    # spec and re-materializes after a restart without the original file.
    src = next(iter(session.sources.values()))
    assert src.content is not None and src.content_encoding == "text"
    assert src.config_snapshot is not None and "content" not in src.config_snapshot


def test_discover_file_inline_csv(mcp: FastMCP, session: ElliotSession):
    out = _tool(mcp, "elliot_discover_source")(
        source_type="csv",
        config={"content": "id,name\n1,Ada\n2,Lin\n", "format": "csv"},
        name="people",
    )
    assert out["row_count"] == 2


def test_discover_from_path_inlines_content(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Discovering via a path (e.g. an uploaded file) inlines the bytes onto
    the source so the published connector no longer depends on that path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ELLIOT_FILE_ROOT", raising=False)
    payload = json.dumps([{"id": 1}, {"id": 2}, {"id": 3}])
    upload = _tool(mcp, "elliot_upload_file")(file_name="data.json", content=payload)
    _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": upload["managed_path"]}, name="d"
    )
    src = next(iter(session.sources.values()))
    assert src.content is not None
    # And it now reads correctly even if the original file disappears.
    Path(upload["managed_path"]).unlink()
    from elliot_core.sources.file_reader import read_file

    assert len(read_file(src).rows) == 3


def test_discover_inline_oversize_rejected(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_MAX_FILE_BYTES", "1024")
    big = json.dumps([{"x": 1}] * 500)
    out = _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"content": big, "format": "json"}, name="big"
    )
    assert _is_error(out) and "FILE_TOO_LARGE" in out.get("text", "")


def test_refresh_file_source_uses_inline_content(mcp: FastMCP, session: ElliotSession):
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"content": '[{"id": 1}, {"id": 2}]', "format": "json"},
        name="people",
    )
    sid = next(iter(session.sources))
    out = _tool(mcp, "elliot_refresh_source")(source_id=sid)
    assert out["row_count"] == 2


def test_discover_path_traversal_still_blocked(
    mcp: FastMCP, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ATTACK: a connector that tries to inline an arbitrary host file (e.g.
    /etc/passwd) via `path` must still be refused by the allowlist."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ELLIOT_FILE_ROOT", str(tmp_path))
    monkeypatch.delenv("ELLIOT_FILE_READER_ALLOW_ABSOLUTE", raising=False)
    secret = tmp_path.parent / "secret.json"
    secret.write_text('[{"pw": "hunter2"}]')
    out = _tool(mcp, "elliot_discover_source")(
        source_type="file", config={"path": str(secret)}, name="x"
    )
    assert _is_error(out) and "FILE_NOT_ALLOWED" in out.get("text", "")


# ---------------------------------------------------------------------------
# elliot_connect_source — design-time interactive OAuth login for discover
# ---------------------------------------------------------------------------


def _oauth_config(url: str = "https://api.example.com/items") -> dict:  # type: ignore[type-arg]
    return {
        "url": url,
        "auth": {
            "type": "oauth2",
            "scope": "per_user",
            "secret_key": "{{ user_oauth:acme }}",
            "oauth2": {
                "authorization_url": "https://acme.example.com/oauth/authorize",
                "token_url": "https://acme.example.com/oauth/token",
                "scopes": ["read"],
                "client_id_secret": "{{ env:ACME_CLIENT_ID }}",
                "client_secret_secret": "{{ env:ACME_CLIENT_SECRET }}",
            },
        },
    }


def test_connect_source_rejects_non_oauth2(mcp: FastMCP):
    result = _tool(mcp, "elliot_connect_source")(
        source_type="rest",
        config={"url": "https://api.example.com/items", "auth": {"type": "bearer", "token": "x"}},
        name="x",
    )
    assert _is_error(result) and "VALIDATION_ERROR" in result["text"]


def test_connect_source_requires_client_id_env(mcp: FastMCP, monkeypatch):
    monkeypatch.delenv("ACME_CLIENT_ID", raising=False)
    result = _tool(mcp, "elliot_connect_source")(
        source_type="rest", config=_oauth_config(), name="acme"
    )
    assert _is_error(result) and "AUTH_REQUIRED" in result["text"]


def test_connect_source_starts_login(mcp: FastMCP, session: ElliotSession, monkeypatch):
    monkeypatch.setenv("ACME_CLIENT_ID", "cid")
    monkeypatch.setenv("ACME_CLIENT_SECRET", "csec")
    try:
        result = _tool(mcp, "elliot_connect_source")(
            source_type="rest", config=_oauth_config(), name="acme"
        )
        assert result["status"] == "awaiting_authorization"
        assert "acme.example.com/oauth/authorize" in result["authorize_url"]
        assert "acme" in session.oauth_logins
    finally:
        login = session.oauth_logins.pop("acme", None)
        if login is not None:
            login.shutdown()


def test_discover_oauth2_without_login_returns_auth_required(mcp: FastMCP):
    """An oauth2 source with no started login and no static token is actionable."""
    result = _tool(mcp, "elliot_discover_source")(
        source_type="rest", config=_oauth_config(), name="acme"
    )
    assert _is_error(result) and "AUTH_REQUIRED" in result["text"]


@respx.mock
async def test_connect_then_discover_oauth2_end_to_end(
    mcp: FastMCP, session: ElliotSession, monkeypatch
):
    """Full flow: connect starts the login, the browser redirect is simulated on
    the loopback port, and discover uses the captured token to fetch the schema."""
    import urllib.request

    from httpx import Response

    monkeypatch.setenv("ACME_CLIENT_ID", "cid")
    monkeypatch.setenv("ACME_CLIENT_SECRET", "csec")

    respx.post("https://acme.example.com/oauth/token").mock(
        return_value=Response(200, json={"access_token": "live-tok"})
    )
    api = respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1, "v": "a"}, {"id": 2, "v": "b"}])
    )

    connect = _tool(mcp, "elliot_connect_source")(
        source_type="rest", config=_oauth_config(), name="acme"
    )
    assert connect["status"] == "awaiting_authorization"

    login = session.oauth_logins["acme"]
    # Simulate the provider redirect landing on the loopback callback (urllib so
    # respx doesn't intercept it).
    with urllib.request.urlopen(
        f"http://127.0.0.1:{login.port}/callback?code=authcode&state={login.state}", timeout=5
    ) as resp:
        assert resp.status == 200

    discover = mcp._tool_manager._tools["elliot_discover_source"].fn
    result = await discover(source_type="rest", config=_oauth_config(), name="acme")

    assert "error" not in result, result
    assert result["row_count"] == 2
    assert result["table_name"] == "acme"
    # The API was called with the captured bearer token.
    assert api.calls.last.request.headers["Authorization"] == "Bearer live-tok"
    # Token stays in memory only — never serialized into a stored SourceConfig.
    dumped = json.dumps([s.model_dump() for s in session.sources.values()])
    assert "live-tok" not in dumped
