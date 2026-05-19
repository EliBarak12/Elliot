"""Tests for source MCP tools: discover, list, preview, profile, refresh, remove."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.source_tools import register_source_tools


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


def test_preview_source_rejects_injection_table_name(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Quote-breaking table_name must be rejected; legit table untouched."""
    csv_path = _csv_file(tmp_path)
    _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    result = _tool(mcp, "elliot_preview_source")(table_name='x" OR 1=1--')
    assert "text" in result
    assert "INVALID_IDENTIFIER" in result["text"]
    assert "items" in session.engine.get_table_names()


def test_discover_source_rejects_injection_name(mcp: FastMCP, session: ElliotSession):
    """A hostile name must be rejected at registration with INVALID_IDENTIFIER
    so it can never become a stored src.table_name."""
    result = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": "/nonexistent.csv"},
        name='evil"; DROP TABLE x',
    )
    assert "text" in result
    assert "INVALID_IDENTIFIER" in result["text"]
    # No source registered at all.
    assert len(session.sources) == 0


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
# elliot_remove_source
# ---------------------------------------------------------------------------


def test_remove_source_removes_from_session(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    sid = disc["source_id"]
    result = _tool(mcp, "elliot_remove_source")(source_id=sid)
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
    _tool(mcp, "elliot_remove_source")(source_id=sid)
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
    _tool(mcp, "elliot_remove_source")(source_id=disc["source_id"])
    result = _tool(mcp, "elliot_preview_source")(table_name="items")
    assert "text" in result or "error" in result


def test_remove_source_not_found_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_remove_source")(source_id="no-such-id")
    assert "text" in result or "error" in result


def test_remove_source_rejects_injection_table_name(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Defense in depth: even if a legacy session file held a hostile
    table_name (registration validation skipped), the remove path must
    refuse rather than f-stringing it into DROP TABLE."""
    csv_path = _csv_file(tmp_path)
    disc = _tool(mcp, "elliot_discover_source")(
        source_type="file",
        config={"path": str(csv_path)},
        name="items",
    )
    sid = disc["source_id"]
    # Mutate the stored config after-the-fact to simulate a tampered session.
    session.sources[sid].table_name = 'items"; DROP TABLE items--'
    result = _tool(mcp, "elliot_remove_source")(source_id=sid)
    assert "text" in result
    assert "INVALID_IDENTIFIER" in result["text"]
    # Legitimate table was not dropped.
    assert "items" in session.engine.get_table_names()


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
