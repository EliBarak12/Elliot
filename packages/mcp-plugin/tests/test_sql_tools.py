"""Tests for SQL MCP tools: query, schema, validate, profile, sample, explain."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from elliot_core.errors import ElliotError
from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.sql_tools import register_sql_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_sql_tools(server, session)
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


def _load_table(session: ElliotSession, tmp_path: Path, name: str = "items") -> None:
    """Load a small CSV fixture into the session engine."""
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / f"{name}.csv"
    p.write_text("id,val\n1,alpha\n2,beta\n3,gamma\n")
    _tool(s, "elliot_discover_source")(source_type="file", config={"path": str(p)}, name=name)


# ---------------------------------------------------------------------------
# elliot_get_schema
# ---------------------------------------------------------------------------


def test_get_schema_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_schema")()
    assert isinstance(result, dict)


def test_get_schema_after_load(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_get_schema")()
    assert "items" in result
    col_names = [c["name"] for c in result["items"]]
    assert "id" in col_names
    assert "val" in col_names


# ---------------------------------------------------------------------------
# elliot_query_sql
# ---------------------------------------------------------------------------


def test_query_sql_valid_select(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_query_sql")(sql='SELECT * FROM "items"')
    assert result["row_count"] == 3
    assert len(result["rows"]) == 3


def test_query_sql_with_where(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_query_sql")(
        sql='SELECT * FROM "items" WHERE id = :id', params={"id": "1"}
    )
    assert result["row_count"] == 1


def test_query_sql_drop_raises(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    # Blocked SQL now raises so FastMCP marks the result isError=true, instead
    # of returning an error dict that looked like a successful result.
    _load_table(session, tmp_path)
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_query_sql")(sql='DROP TABLE "items"')


def test_query_sql_insert_raises(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_query_sql")(sql="INSERT INTO items VALUES (4, 'delta')")


def test_query_sql_empty_raises(mcp: FastMCP):
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_query_sql")(sql="  ")


def test_query_sql_semicolon_rejected(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_query_sql")(sql='SELECT 1; DROP TABLE "items"')


# ---------------------------------------------------------------------------
# elliot_list_tables
# ---------------------------------------------------------------------------


def test_list_tables_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_list_tables")()
    assert result["tables"] == []


def test_list_tables_after_load(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_list_tables")()
    assert "items" in result["tables"]


# ---------------------------------------------------------------------------
# elliot_validate_sql
# ---------------------------------------------------------------------------


def test_validate_sql_valid_select(mcp: FastMCP):
    result = _tool(mcp, "elliot_validate_sql")(sql="SELECT id, val FROM items")
    assert result["valid"] is True
    assert result["reason"] == ""


def test_validate_sql_drop_invalid(mcp: FastMCP):
    result = _tool(mcp, "elliot_validate_sql")(sql="DROP TABLE items")
    assert result["valid"] is False
    assert result["reason"] != ""


def test_validate_sql_empty_invalid(mcp: FastMCP):
    result = _tool(mcp, "elliot_validate_sql")(sql="")
    assert result["valid"] is False


def test_validate_sql_semicolon_invalid(mcp: FastMCP):
    result = _tool(mcp, "elliot_validate_sql")(sql="SELECT 1; SELECT 2")
    assert result["valid"] is False


# ── H4: schema-aware validation once data is loaded ─────────────────────────


def test_validate_sql_flags_unknown_table(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)  # loads table "items"
    result = _tool(mcp, "elliot_validate_sql")(sql="SELECT id FROM nope")
    assert result["valid"] is False
    assert "nope" in result["reason"]
    assert result["missing_tables"] == ["nope"]


def test_validate_sql_accepts_known_table(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)  # loads table "items"
    result = _tool(mcp, "elliot_validate_sql")(sql="SELECT id FROM items")
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# elliot_sample_data
# ---------------------------------------------------------------------------


def test_sample_data_returns_rows(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_sample_data")(table_name="items")
    assert "rows" in result
    assert len(result["rows"]) <= 10


def test_sample_data_limit(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_sample_data")(table_name="items", limit=2)
    assert len(result["rows"]) <= 2


def test_sample_data_missing_table_raises(mcp: FastMCP):
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_sample_data")(table_name="ghost")


# ---------------------------------------------------------------------------
# elliot_profile_column
# ---------------------------------------------------------------------------


def test_profile_column_returns_stats(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_profile_column")(table_name="items", column_name="val")
    assert "distinct_count" in result or "null_count" in result or isinstance(result, dict)


def test_profile_column_missing_table_raises(mcp: FastMCP):
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_profile_column")(table_name="ghost", column_name="x")


# ---------------------------------------------------------------------------
# elliot_explain_query
# ---------------------------------------------------------------------------


def test_explain_query_returns_plan(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "elliot_explain_query")(sql='SELECT * FROM "items"')
    assert "plan" in result


def test_explain_query_invalid_sql_raises(mcp: FastMCP):
    with pytest.raises(ElliotError):
        _tool(mcp, "elliot_explain_query")(sql="NOT VALID SQL !!!")


# ---------------------------------------------------------------------------
# Identifier-injection / read-only regressions
# ---------------------------------------------------------------------------


def test_sample_data_rejects_quote_injection(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    """A table name carrying a double-quote must be rejected by safe_ident,
    not f-stringed into the query where it could break out of the identifier."""
    _load_table(session, tmp_path)
    with pytest.raises(ElliotError) as exc:
        _tool(mcp, "elliot_sample_data")(table_name='items" UNION SELECT 1 --')
    assert exc.value.code == "INVALID_IDENTIFIER"


def test_explain_query_rejects_non_select(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    """EXPLAIN must not plan a non-read-only statement."""
    _load_table(session, tmp_path)
    with pytest.raises(ElliotError) as exc:
        _tool(mcp, "elliot_explain_query")(sql='DROP TABLE "items"')
    assert exc.value.code == "INVALID_SQL"
